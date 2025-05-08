# bot.py
import discord
from discord.ext import commands
import os
import json
import logging
import re
import requests
from report import Report
import asyncio
from datetime import datetime, timedelta
from enum import Enum, auto

# Set up logging to the console
logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

# There should be a file called 'tokens.json' inside the same folder as this file
token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    # If you get an error here, it means your token is formatted incorrectly. Did you put it in quotes?
    tokens = json.load(f)
    discord_token = tokens['discord']


class ModAction(Enum):
    REPORT_TO_LAW = auto()
    BAN_USER = auto()
    DECREASE_SCORE = auto()
    SUSPEND_ACCOUNT = auto()
    NO_ACTION = auto()
    SKIP = auto()


class ModReport:
    def __init__(self, reporter_id, reported_user_id, message, reason, details, score=50):
        self.reporter_id = reporter_id
        self.reported_user_id = reported_user_id
        self.message = message
        self.reason = reason
        self.details = details
        self.score = score
        self.timestamp = datetime.now()
        self.status = "pending"
        self.mod_actions = []


class ModBot(discord.Client):
    def __init__(self): 
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} # Map from guild to the mod channel id for that guild
        self.reports = {} # Map from user IDs to the state of their report

        self.mod_reports = [] # List of reports to be handled by moderators
        self.current_report_index = -1 # Index of currently viewed report
        self.user_scores = {} # Map from user IDs to their trust scores

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        # Parse the group number out of the bot's name
        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        # Find the mod channel in each guild that this bot should report to
        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel
        
        # print(f"Mod channels set up: {self.mod_channels}")

    async def on_message(self, message):
        '''
        This function is called whenever a message is sent in a channel that the bot can see (including DMs). 
        Currently the bot is configured to only handle messages that are sent over DMs or in your group's "group-#" channel. 
        '''
        # Ignore messages from the bot 
        if message.author.id == self.user.id:
            return

        # Check if this message was sent in a server ("guild") or if it's a DM
        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)

    async def handle_dm(self, message):
        # Handle a help message
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        # Only respond to messages if they're part of a reporting flow
        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        # If we don't currently have an active report for this user, add one
        if author_id not in self.reports:
            self.reports[author_id] = Report(self)

        # Let the report class handle this message; forward all the messages it returns to us
        responses = await self.reports[author_id].handle_message(message)
        for r in responses:
            await message.channel.send(r)

        # If the report is complete or cancelled, remove it from our map
        if self.reports[author_id].report_complete():
            self.reports.pop(author_id)

    async def handle_channel_message(self, message):
        # print(f"Channel message: {message.channel.name}")
        # print(f"Mod channels: {self.mod_channels}")
        # print(f"Message content: {message.content}")
        
        # Check if this is a message in the mod channel
        for guild_id, mod_channel in self.mod_channels.items():
            if message.channel.id == mod_channel.id:
                print(f"This is a mod channel message")
                if message.content.startswith('!'):
                    print(f"This is a mod command: {message.content}")
                    await self.handle_mod_command(message)
                return
        
        # Only handle messages sent in the "group-#" channel
        if message.channel.name == f'group-{self.group_num}':
            # Forward the message to the mod channel
            mod_channel = self.mod_channels[message.guild.id]
            
            # Evaluate the message content
            evaluation = self.eval_text(message.content)
            
            # Format and send to mod channel
            await mod_channel.send(f'Forwarded message:\n{message.author.name}: "{message.content}"')
            await mod_channel.send(self.code_format(evaluation))

    async def handle_mod_command(self, message):
        """Handle moderator commands in the mod channel"""
        # print(f"Handling mod command: {message.content}")

        content = message.content.strip().lower()
        
        # Process commands
        if content == '!queue':
            await self.show_report_queue(message.channel)
        elif content == '!next':
            await self.show_next_report(message.channel)
        elif content.startswith('!view'):
            await self.view_report_details(message.channel, content)
        elif content.startswith('!action'):
            await self.handle_mod_action(message.channel, content)
        elif content.startswith('!search'):
            await self.search_messages(message.channel, content)
        elif content.startswith('!help'):
            await self.show_mod_help(message.channel)
    
    async def show_report_queue(self, channel):
        """Show a list of pending reports"""
        if not self.mod_reports:
            await channel.send("No reports in the queue.")
            return
        
        pending_reports = [r for r in self.mod_reports if r.status == "pending"]
        if not pending_reports:
            await channel.send("No pending reports in the queue.")
            return
        
        embed = discord.Embed(title="Report Queue", color=discord.Color.blue())
        for i, report in enumerate(pending_reports):
            embed.add_field(
                name=f"Report #{i+1}: {report.reason}", 
                value=f"From: <@{report.reporter_id}> | Against: <@{report.reported_user_id}> | Score: {report.score}",
                inline=False
            )
        await channel.send(embed=embed)

    async def show_next_report(self, channel):
        """Show the next report in the queue"""
        if not self.mod_reports:
            await channel.send("No reports in the queue.")
            return
        
        # Finding the next pending report
        for _ in range(len(self.mod_reports)):
            self.current_report_index = (self.current_report_index + 1) % len(self.mod_reports)
            if self.mod_reports[self.current_report_index].status == "pending":
                break
        else:
            await channel.send("No pending reports in the queue.")
            return
        
        report = self.mod_reports[self.current_report_index]
        
        embed = discord.Embed(
            title=f"Report: {report.reason}",
            description=f"Score: {report.score}",
            color=discord.Color.red() if report.score < 30 else discord.Color.orange()
        )
        embed.add_field(name="Reporter", value=f"<@{report.reporter_id}>", inline=True)
        embed.add_field(name="Reported User", value=f"<@{report.reported_user_id}>", inline=True)
        embed.add_field(name="Details", value=report.details, inline=False)
        embed.add_field(name="Status", value=report.status, inline=False)
        embed.add_field(name="Options", value="Use `!view thread` to see the full message thread\n"
                                         "Use `!view message` to see the reported message\n"
                                         "Use `!search [keywords]` to search for keywords\n"
                                         "Use `!action [type]` to take action", inline=False)
        await channel.send(embed=embed)


    async def view_report_details(self, channel, content):
        """View detailed information about the current report"""
        if not self.mod_reports or self.current_report_index < 0:
            await channel.send("No report currently selected. Use `!next` to select a report.")
            return
        
        report = self.mod_reports[self.current_report_index]
        
        parts = content.split()
        if len(parts) < 2:
            await channel.send("Please specify what to view: `!view thread` or `!view message`")
            return
        
        view_type = parts[1]
        if view_type == "thread":
            await self.view_message_thread(channel, report)
        elif view_type == "message":
            await self.view_reported_message(channel, report)
        else:
            await channel.send("Unknown view type. Use `thread` or `message`.")


    async def view_message_thread(self, channel, report):
        """Show the full message thread around the reported message"""
        message = report.message
        if not message:
            await channel.send("Message not available.")
            return
        
        # Getting the guild and channel where the message was sent
        guild = self.get_guild(message.guild.id)
        if not guild:
            await channel.send("Cannot access the guild where this message was sent.")
            return
        
        text_channel = guild.get_channel(message.channel.id)
        if not text_channel:
            await channel.send("Cannot access the channel where this message was sent.")
            return
        
        try:
            
            messages = []
            async for msg in text_channel.history(limit=10, around=message):
                messages.append(msg)
            messages.sort(key=lambda m: m.created_at)
            
            embed = discord.Embed(title="Message Thread", description=f"Channel: {text_channel.name}", color=discord.Color.blue())
            for msg in messages:
                embed.add_field(
                    name=f"{msg.author.name} ({msg.created_at.strftime('%Y-%m-%d %H:%M')})",
                    value=msg.content[:1024] if msg.content else "(No content)",
                    inline=False
                )
            await channel.send(embed=embed)
        except Exception as e:
            await channel.send(f"Error retrieving message thread: {str(e)}")


    async def view_reported_message(self, channel, report):
        """Show just the reported message"""
        message = report.message
        if not message:
            await channel.send("Message not available.")
            return
        
        embed = discord.Embed(
            title="Reported Message",
            description=f"From: {message.author.name}",
            color=discord.Color.red()
        )
        embed.add_field(name="Content", value=message.content[:1024] if message.content else "(No content)", inline=False)
        embed.add_field(name="Sent At", value=message.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        embed.add_field(name="Channel", value=message.channel.name, inline=True)
        await channel.send(embed=embed)


    async def search_messages(self, channel, content):
        """Search for keywords in the message history"""
        if not self.mod_reports or self.current_report_index < 0:
            await channel.send("No report currently selected. Use `!next` to select a report.")
            return
        
        report = self.mod_reports[self.current_report_index]
        
        parts = content.split(maxsplit=1)
        if len(parts) < 2:
            await channel.send("Please provide search keywords: `!search [keywords]`")
            return
        
        keywords = parts[1].lower().split()
        message = report.message
        
        guild = self.get_guild(message.guild.id)
        if not guild:
            await channel.send("Cannot access the guild where this message was sent.")
            return
        
        text_channel = guild.get_channel(message.channel.id)
        if not text_channel:
            await channel.send("Cannot access the channel where this message was sent.")
            return
        
        # Searching for messages with keywords
        try:
            messages = await text_channel.history(limit=100).flatten()
            matching_messages = []
            
            for msg in messages:
                if msg.author.id == report.reported_user_id:
                    content_lower = msg.content.lower()
                    if any(keyword in content_lower for keyword in keywords):
                        matching_messages.append(msg)
            
            if not matching_messages:
                await channel.send(f"No messages found containing the keywords: {', '.join(keywords)}")
                return
            
            embed = discord.Embed(
                title=f"Messages Containing Keywords", 
                description=f"Found {len(matching_messages)} messages with keywords: {', '.join(keywords)}",
                color=discord.Color.gold()
            )
            
            for i, msg in enumerate(matching_messages[:10]):  # Limit to 10 messages
                embed.add_field(
                    name=f"Message {i+1} ({msg.created_at.strftime('%Y-%m-%d %H:%M')})",
                    value=msg.content[:1024] if msg.content else "(No content)",
                    inline=False
                )
            
            if len(matching_messages) > 10:
                embed.set_footer(text=f"Showing 10 of {len(matching_messages)} matching messages")
            
            await channel.send(embed=embed)
        except Exception as e:
            await channel.send(f"Error searching messages: {str(e)}")


    async def handle_mod_action(self, channel, content):
        """Handle moderator actions on reports"""
        if not self.mod_reports or self.current_report_index < 0:
            await channel.send("No report currently selected. Use `!next` to select a report.")
            return
        
        report = self.mod_reports[self.current_report_index]
        
        parts = content.split()
        if len(parts) < 2:
            await channel.send("Please specify an action: `!action [ban|suspend|decrease|report|none|skip]`")
            return
        
        action_type = parts[1].lower()
        
        if action_type == "ban":
            await self.ban_user(channel, report)
        elif action_type == "suspend":
            if len(parts) < 3:
                await channel.send("Please specify suspension duration: `!action suspend [days]`")
                return
            try:
                days = int(parts[2])
                await self.suspend_user(channel, report, days)
            except ValueError:
                await channel.send("Invalid duration. Please use a number of days.")
        elif action_type == "decrease":
            # Decreasing the user's score
            if len(parts) < 3:
                await channel.send("Please specify new score: `!action decrease [new_score]`")
                return
            try:
                new_score = int(parts[2])
                await self.decrease_user_score(channel, report, new_score)
            except ValueError:
                await channel.send("Invalid score. Please use a number.")
        elif action_type == "report":
            await self.report_to_law(channel, report)
        elif action_type == "none": # Taking no action
            report.status = "completed"
            report.mod_actions.append(ModAction.NO_ACTION)
            await channel.send("No action taken. Report marked as complete.")
        elif action_type == "skip":
            await channel.send("Report skipped. Use `!next` to move to the next report.")
        else:
            await channel.send("Unknown action type. Use `ban`, `suspend`, `decrease`, `report`, `none`, or `skip`.")


    async def ban_user(self, channel, report):
        """Ban a user"""
        guild = self.get_guild(report.message.guild.id)
        if not guild:
            await channel.send("Cannot access the guild for this report.")
            return
        
        try:
            member = await guild.fetch_member(report.reported_user_id)
            if not member:
                await channel.send("Cannot find the reported user in the guild.")
                return
            
            # Confirming before banning
            confirm_msg = await channel.send(f"Are you sure you want to ban {member.name}? React with ✅ to confirm or ❌ to cancel.")
            await confirm_msg.add_reaction("✅")
            await confirm_msg.add_reaction("❌")
            
            def check(reaction, user):
                return user == channel.last_message.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
            
            try:
                reaction, user = await self.wait_for('reaction_add', timeout=60.0, check=check)
                
                if str(reaction.emoji) == "✅":
                    await guild.ban(member, reason=f"Banned by moderator for {report.reason}")
                    report.status = "completed"
                    report.mod_actions.append(ModAction.BAN_USER)
                    await channel.send(f"User {member.name} has been banned.")
                else:
                    await channel.send("Ban canceled.")
            except asyncio.TimeoutError:
                await channel.send("Ban action timed out.")
        except Exception as e:
            await channel.send(f"Error banning user: {str(e)}")

    async def suspend_user(self, channel, report, days):
        """Suspend a user (simulated by timeout)"""
        guild = self.get_guild(report.message.guild.id)
        if not guild:
            await channel.send("Cannot access the guild for this report.")
            return
        
        try:
            member = await guild.fetch_member(report.reported_user_id)
            if not member:
                await channel.send("Cannot find the reported user in the guild.")
                return
            
            # This is For Discord servers with timeout support
            until = datetime.now() + timedelta(days=days)
            await member.timeout(until, reason=f"Timed out for {report.reason}")
            
            report.status = "completed"
            report.mod_actions.append(ModAction.SUSPEND_ACCOUNT)
            await channel.send(f"User {member.name} has been suspended for {days} days (until {until.strftime('%Y-%m-%d %H:%M')}).")
        except Exception as e:
            await channel.send(f"Error suspending user: {str(e)}")

    async def decrease_user_score(self, channel, report, new_score):
        """Decrease a user's trust score"""
        if new_score < 0 or new_score > 100:
            await channel.send("Score must be between 0 and 100.")
            return
        self.user_scores[report.reported_user_id] = new_score
        
        report.status = "completed"
        report.mod_actions.append(ModAction.DECREASE_SCORE)
        await channel.send(f"User's trust score has been updated to {new_score}.")


    async def report_to_law(self, channel, report):
        """This will simulate Simulate reporting to law enforcement. 
        Since this is not integrated with any real system, we'll just mark the report and notify """
        
        confirm_msg = await channel.send(f"Are you sure you want to report this to law enforcement? React with ✅ to confirm or ❌ to cancel.")
        await confirm_msg.add_reaction("✅")
        await confirm_msg.add_reaction("❌")
        
        def check(reaction, user):
            return user == channel.last_message.author and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
        
        try:
            reaction, user = await self.wait_for('reaction_add', timeout=60.0, check=check)
            
            if str(reaction.emoji) == "✅":
                report.status = "completed"
                report.mod_actions.append(ModAction.REPORT_TO_LAW)
                await channel.send("This incident has been flagged for law enforcement reporting.")
            else:
                await channel.send("Law enforcement reporting canceled.")
        except asyncio.TimeoutError:
            await channel.send("Law enforcement reporting action timed out.")


    async def show_mod_help(self, channel):
        """Show help for moderator commands"""
        embed = discord.Embed(title="Moderator Commands Help", color=discord.Color.blue())
        embed.add_field(name="!queue", value="Show pending reports in the queue", inline=False)
        embed.add_field(name="!next", value="View the next report in the queue", inline=False)
        embed.add_field(name="!view thread", value="View the full message thread around the reported message", inline=False)
        embed.add_field(name="!view message", value="View just the reported message", inline=False)
        embed.add_field(name="!search [keywords]", value="Search for messages with keywords", inline=False)
        embed.add_field(name="!action ban", value="Ban the reported user", inline=False)
        embed.add_field(name="!action suspend [days]", value="Suspend the user for specified days", inline=False)
        embed.add_field(name="!action decrease [score]", value="Set a new trust score for the user", inline=False)
        embed.add_field(name="!action report", value="Report to law enforcement", inline=False)
        embed.add_field(name="!action none", value="Take no action and mark report as complete", inline=False)
        embed.add_field(name="!action skip", value="Skip this report for now", inline=False)
        embed.add_field(name="!help", value="Show this help message", inline=False)
        await channel.send(embed=embed)
    



    def eval_text(self, message):
        """
        Evaluate the message text for potential child safety issues.
        Returns a dictionary with evaluation scores and flags.
        """
        evaluation = {
            "score": 100, 
            "flags": []
        }
        
        child_safety_keywords = [
            "meet up", "meetup", "where do you live", "how old are you", 
            "send pic", "send photo", "don't tell", "our secret", "keep secret",
            "alone", "private", "just us", "dm me", "message me"
        ]
        
        msg_lower = message.lower()
        for keyword in child_safety_keywords:
            if keyword in msg_lower:
                evaluation["score"] -= 20
                evaluation["flags"].append(f"Child safety concern: '{keyword}'")
        
        if len(message) < 5:
            evaluation["score"] -= 5
            evaluation["flags"].append("Very short message")
        elif len(message) > 500:
            evaluation["score"] -= 10
            evaluation["flags"].append("Very long message")
        
        evaluation["score"] = max(0, min(100, evaluation["score"]))
        
        return evaluation

    
    def code_format(self, evaluation):
        """Format the evaluation results for display in the mod channel"""
        result = f"**Message Score: {evaluation['score']}/100**\n"
        
        if evaluation["flags"]:
            result += "**Flags:**\n"
            for flag in evaluation["flags"]:
                result += f"- {flag}\n"
        else:
            result += "No flags detected."
        
        # Adding color formatting based on score
        if evaluation["score"] < 30:
            return f"```diff\n- {result}\n```"  # Red formatting
        elif evaluation["score"] < 70:
            return f"```fix\n{result}\n```"  # Yellow formatting
        else:
            return f"```\n{result}\n```"  # Normal formatting
        
    def add_report_to_queue(self, report_data):
        """Add a report to the moderation queue from report data"""
        new_report = ModReport(
            reporter_id=report_data["reporter_id"],
            reported_user_id=report_data["reported_user_id"],
            message=report_data["message"],
            reason=report_data["reason"],
            details=report_data["details"],
            score=report_data["score"]
        )
        self.mod_reports.append(new_report)


client = ModBot()
client.run(discord_token)