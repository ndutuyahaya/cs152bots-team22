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
from backend import bot_backend as ustats
from datetime import datetime, timedelta
from enum import Enum, auto
import csv

try:
    from classifier import GroomingClassifier, ConversationBuffer, UserRiskProfile
    ML_AVAILABLE = True
except ImportError as e:
    print(f"ML components not available: {e}")
    ML_AVAILABLE = False

logger = logging.getLogger('discord')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)


token_path = 'tokens.json'
if not os.path.isfile(token_path):
    raise Exception(f"{token_path} not found!")
with open(token_path) as f:
    tokens = json.load(f)
    discord_token = tokens['discord']


class ModAction(Enum):
    REPORT_TO_LAW = auto()
    BAN_USER = auto()
    INCREASE_SCORE = auto()
    SUSPEND_ACCOUNT = auto()
    NO_ACTION = auto()
    SKIP = auto()


class ModReport:
    """
    Class which contains object instances representing a report.
    """
    def __init__(self, reporter_id, reported_user_id, message, reason, details, score=50, ml_prediction=None):
        self.reporter_id = reporter_id
        self.reported_user_id = reported_user_id
        self.message = message
        self.reason = reason
        self.details = details
        self.score = score
        self.ml_prediction = ml_prediction  # ML predicition results
        self.timestamp = datetime.now()
        self.status = "pending"
        self.mod_actions = []


class ModBot(discord.Client):
    def __init__(self): 
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix='.', intents=intents)
        self.group_num = None
        self.mod_channels = {} 
        self.reports = {} 
        self.mod_reports = [] 
        self.current_report_index = -1 
        self.user_scores = {} 

        self.classifier = None
        self.conversation_buffer = None
        self.risk_profiles = None
        
        if ML_AVAILABLE:
            try:
                self.classifier = GroomingClassifier()
                self.conversation_buffer = ConversationBuffer(max_messages=50, time_window_hours=24)
                self.risk_profiles = UserRiskProfile()
                logging.info("ML components initialized successfully")
                print("✅ ML components loaded successfully")
            except Exception as e:
                logging.error(f"Failed to initialize ML components: {e}")
                print(f"❌ Failed to load ML components: {e}")
                print("🔄 Bot will not function without ML components")
                raise e
        else:
            print("⚠️ ML components not available - bot cannot function")
            raise Exception("ML components required for bot operation")
        
        # Initialize backend database upon bot initialization2
        ustats.initialize_database()

    def save_flagged_conversation(self, user_id, message, ml_prediction, risk_assessment, conversation_context=None):
        """Save flagged conversations to a CSV file with enhanced tracking"""
        filename = f"flagged_conversations_{datetime.now().strftime('%Y%m%d')}.csv"
        
        conversation_id = self.generate_conversation_id(message, conversation_context)
        
        # Data to save
        row_data = {
            'timestamp': datetime.now().isoformat(),
            'message_id': message.id, 
            'conversation_id': conversation_id,  
            'user_id': user_id,
            'username': message.author.name,
            'guild_id': message.guild.id,
            'guild_name': message.guild.name,
            'channel_id': message.channel.id,
            'channel_name': message.channel.name,
            'message_content': message.content,
            'grooming_probability': ml_prediction.get('grooming_probability', 0) if ml_prediction else 0,
            'model_confidence': ml_prediction.get('confidence', 0) if ml_prediction else 0,
            'risk_level': risk_assessment.get('risk_level', 'unknown'),
            'risk_score': risk_assessment.get('risk_score', 0),
            'should_escalate': risk_assessment.get('should_escalate', False),
            'escalation_reason': risk_assessment.get('escalation_reason', ''),
            'conversation_context_length': len(conversation_context) if conversation_context else 1,
            'created_at': message.created_at.isoformat()  
        }
        
        file_exists = os.path.exists(filename)
        
        with open(filename, 'a', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=row_data.keys())
            
            if not file_exists:
                writer.writeheader()
            
            writer.writerow(row_data)
        
        print(f"📝 Flagged conversation saved to {filename} (Conversation ID: {conversation_id})")

    def generate_conversation_id(self, message, conversation_context=None):
        """Creates and generates a conversation ID based on time buckets."""
        time_window_minutes = 30
        time_bucket = int(message.created_at.timestamp() // (time_window_minutes * 60))
        
        conversation_id = f"{message.channel.id}_{message.author.id}_{time_bucket}"
        
        if conversation_context and len(conversation_context) > 1:
            earliest_msg = min(conversation_context, key=lambda m: m.created_at)
            earliest_time_bucket = int(earliest_msg.created_at.timestamp() // (time_window_minutes * 60))
            conversation_id = f"{message.channel.id}_{message.author.id}_{earliest_time_bucket}"
        
        return conversation_id

    def save_user_profiles(self):
        """Save all user risk profiles to JSON"""
        if not self.risk_profiles:
            return
        
        filename = f"user_risk_profiles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
        profiles_data = {}
        for user_id, profile in self.risk_profiles.user_profiles.items():
            profiles_data[str(user_id)] = {
                'risk_score': profile['risk_score'],
                'total_messages': profile['total_messages'],
                'flagged_messages': profile['flagged_messages'],
                'last_updated': profile['last_updated'].isoformat(),
                'highest_risk_score': profile['highest_risk_score'],
                'predictions_history': [
                    {
                        'timestamp': pred['timestamp'].isoformat(),
                        'grooming_probability': pred['grooming_probability'],
                        'confidence': pred['confidence'],
                        'predicted_class': pred['predicted_class']
                    }
                    for pred in profile['predictions_history']
                ]
            }
        
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(profiles_data, f, indent=2, ensure_ascii=False)
        
        print(f"👤 User profiles saved to {filename}")

    def export_flagged_users_report(self):
        """Export a summary report of all flagged users with their IDs"""
        if not self.risk_profiles:
            return
        
        filename = f"flagged_users_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'user_id', 'risk_score', 'risk_level', 'total_messages', 
                'flagged_messages', 'should_escalate', 'escalation_reason',
                'last_updated', 'highest_risk_score'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for user_id, profile in self.risk_profiles.user_profiles.items():
                risk_level, _ = self.risk_profiles.get_user_risk_level(user_id)
                should_escalate, escalation_reason = self.risk_profiles.should_escalate(user_id)
                
                writer.writerow({
                    'user_id': user_id,
                    'risk_score': round(profile['risk_score'], 2),
                    'risk_level': risk_level,
                    'total_messages': profile['total_messages'],
                    'flagged_messages': profile['flagged_messages'],
                    'should_escalate': should_escalate,
                    'escalation_reason': escalation_reason,
                    'last_updated': profile['last_updated'].isoformat(),
                    'highest_risk_score': round(profile['highest_risk_score'], 2)
                })
        
        print(f"📊 Flagged users report exported to {filename}")

    async def on_ready(self):
        print(f'{self.user.name} has connected to Discord! It is these guilds:')
        for guild in self.guilds:
            print(f' - {guild.name}')
        print('Press Ctrl-C to quit.')

        match = re.search('[gG]roup (\d+) [bB]ot', self.user.name)
        if match:
            self.group_num = match.group(1)
        else:
            raise Exception("Group number not found in bot's name. Name format should be \"Group # Bot\".")

        for guild in self.guilds:
            for channel in guild.text_channels:
                if channel.name == f'group-{self.group_num}-mod':
                    self.mod_channels[guild.id] = channel
        
        print(f"🤖 Pure ML Detection Active - Model: {self.classifier.model_path}")


    async def on_message(self, message): 
        if message.author.id == self.user.id:
            return
        if message.guild:
            await self.handle_channel_message(message)
        else:
            await self.handle_dm(message)


    async def handle_dm(self, message):
        if message.content == Report.HELP_KEYWORD:
            reply =  "Use the `report` command to begin the reporting process.\n"
            reply += "Use the `cancel` command to cancel the report process.\n"
            await message.channel.send(reply)
            return

        author_id = message.author.id
        responses = []

        if author_id not in self.reports and not message.content.startswith(Report.START_KEYWORD):
            return

        if author_id not in self.reports:
            self.reports[author_id] = Report(self)

        responses = await self.reports[author_id].handle_message(message)
        for r in responses:
            await message.channel.send(r)

        if self.reports[author_id].report_complete():
            self.reports.pop(author_id)

    async def handle_channel_message(self, message):
        for guild_id, mod_channel in self.mod_channels.items():
            if message.channel.id == mod_channel.id:
                if message.content.startswith('!'):
                    await self.handle_mod_command(message)
                return
        # Handle all regular channel messages to process grooming risk with ML.
        if message.channel.name == f'group-{self.group_num}':
            await self.process_message_with_ml(message)

    async def process_message_with_ml(self, message):
        try:
            # Following lines use context of convo to predict grooming probability.
            self.conversation_buffer.add_message(message.author.id, message)
            
            conversation_context = self.conversation_buffer.get_conversation_context(
                message.author.id, include_recent=10
            )
            
            if len(conversation_context) < 2:
                conversation_context = [message]
            
            conversation_text = self.classifier.format_conversation_for_prediction(conversation_context)
            ml_prediction = self.classifier.predict_grooming_probability(conversation_text)
            
            risk_profile = self.risk_profiles.update_user_score(
                message.author.id, 
                ml_prediction,
                message_context=message.content
            )
            
            risk_level, risk_score = self.risk_profiles.get_user_risk_level(message.author.id)
            should_escalate, escalation_reason = self.risk_profiles.should_escalate(message.author.id)
            
            risk_assessment = {
                'risk_level': risk_level,
                'risk_score': risk_score,
                'should_escalate': should_escalate,
                'escalation_reason': escalation_reason,
                'total_messages': risk_profile['total_messages'],
                'flagged_messages': risk_profile['flagged_messages']
            }
            
            should_save = False
            if ml_prediction and not ml_prediction.get('error'):
                prob = ml_prediction.get('grooming_probability', 0)
                conf = ml_prediction.get('confidence', 0)
                # Checking if prediction results are large enough to flag.
                if prob > self.risk_profiles.grooming_threshold and conf > self.risk_profiles.confidence_threshold:
                    should_save = True
            
            if risk_assessment and risk_assessment.get('should_escalate', False):
                should_save = True
            # Track the flagged convo.
            if should_save:
                self.save_flagged_conversation(message.author.id, message, ml_prediction, risk_assessment, conversation_context)

            mod_channel = self.mod_channels[message.guild.id]
            await self.send_ml_analysis_to_mod_channel(
                mod_channel, message, ml_prediction, risk_assessment, conversation_context
            )
            # For riskiest of conversations, immediately escalate
            if risk_assessment['should_escalate']:
                await self.auto_escalate_user(message, ml_prediction, risk_assessment)
            
            # We want to store info of those who we need to log.
            if ml_prediction and not ml_prediction.get('error') :
                if prob > self.risk_profiles.grooming_threshold and conf > self.risk_profiles.confidence_threshold:       
                    grooming_suspected = True
                else:
                    grooming_suspected = False # Keep it binary, false means no/undetermrined
                user_id = message.author.id
                username = message.author.name
                message_id = message.id

                conversation_id = self.generate_conversation_id(message, conversation_context)
                mod_channel = self.mod_channels[message.guild.id]

                if not ustats.check_user_exists(user_id):
                    ustats.add_user(user_id, username)

                risk_level, ml_risk_score = self.risk_profiles.get_user_risk_level(user_id)

                ustats.log_conversation(user_id, message_id, conversation_id, conf, grooming_suspected, ml_risk_score)

                await self.handle_backend_updates(user_id, username, message, mod_channel)
                
        except Exception as e:
            logging.error(f"Error in ML processing: {e}")
            mod_channel = self.mod_channels[message.guild.id]
            await mod_channel.send(f"❌ **ML Processing Error:** {str(e)}")
    

    async def handle_backend_updates(self, user_id, username, message, mod_channel):
        """Handles checking backend updates and conducting moderator actions."""
        try:
            # First gather current risk_score and update that in the backend
            user_info = ustats.get_user_stats(user_id)

            # Note, this risk score differs from the ml_risk_score in that it weighs messages.
            if user_info.get('risk_score', 50) > ustats.REPORT_THRESHOLD and not user_info['reported_law']:
                ustats.update_report_to_law(user_id, username, True, True)
                await self.autoreport_user(message, mod_channel) 

            elif user_info.get('risk_score', 50) > ustats.BAN_THRESHOLD and not user_info['banned']:
                ustats.update_ban(user_id, username, True)
                await self.autoban_user(message, mod_channel)

            elif user_info.get('risk_score', 50) > ustats.SUSPEND_THRESHOLD and not user_info['suspended'] and not user_info['banned']:
                # Suspension length dependent on org policy.
                suspension_length = 30
                ustats.update_suspension(user_id, username, True, suspension_length)
                await self.autosuspend_user(message, mod_channel, suspension_length)

            else:
                return
            
        except Exception as e:
            await mod_channel.send(f"Error updating database for user: {str(e)}")


    async def autosuspend_user(self, message, mod_channel, length):
        """Suspend a user"""
        guild = self.get_guild(message.guild.id)
        if not guild:
            await mod_channel.send("Cannot access the guild for this report.")
            return
        try:
            member = await guild.fetch_member(message.author.id)
            if not member:
                await mod_channel.send("Cannot find the reported user in the guild.")
                return
            
            await self.send_consequence_analysis_to_mod_channel(message, mod_channel, 0, length)
        except Exception as e:
            await mod_channel.send(f"Error suspending user: {str(e)}")


    async def autoban_user(self, message, mod_channel):
        """Ban a user"""
        guild = self.get_guild(message.guild.id)
        if not guild:
            await mod_channel.send("Cannot access the guild for this report.")
            return
        try:
            member = await guild.fetch_member(message.author.id)
            if not member:
                await mod_channel.send("Cannot find the reported user in the guild.")
                return
            ### UNCHECK TO ACTUALLY BAN ###
            # await guild.ban(member, reason=f"{member.name} has been banned for violating TOS.")
            await self.send_consequence_analysis_to_mod_channel(message, mod_channel, 1)
        except Exception as e:
            await mod_channel.send(f"Error banning user: {str(e)}")  


    async def autoreport_user(self, message, mod_channel):
        """Suspend a user"""
        guild = self.get_guild(message.guild.id)
        if not guild:
            await mod_channel.send("Cannot access the guild for this report.")
            return
        try:
            member = await guild.fetch_member(message.author.id)
            if not member:
                await mod_channel.send("Cannot find the reported user in the guild.")
                return

            await self.send_consequence_analysis_to_mod_channel(message, mod_channel, 2)
        except Exception as e:
            await mod_channel.send(f"Error reporting user to law enforcement: {str(e)}")


    async def send_consequence_analysis_to_mod_channel(self, message, mod_channel, consequence, suspension_len=0):
        """
        Send message alerting of any bans, suspensions, reports to law enforcement.

        Consequence: Can be of values 0, 1, or >=2 indicating suspension, ban, or report 
        to law enforcement respectively.
        """
        if consequence == 0:
            alert_embed = discord.Embed(
                    title="🚨 BOT ALERT",
                    description=f"**User {message.author.name}** has been suspended for {suspension_len} days.",
                    color=discord.Color.red()
                )
            alert_embed.add_field(
                name="🎯 Reason", 
                value="Engaging in potential child grooming activities.", 
                inline=False
            )
        elif consequence == 1:
            alert_embed = discord.Embed(
                    title="🚨 BOT ALERT",
                    description=f"**User {message.author.name}** has been banned due to violating Terms of Service.",
                    color=discord.Color.red()
                )
            alert_embed.add_field(
                name="🎯 Reason", 
                value="Engaging in child grooming activities.",
                inline=False
            )
        else: 
            alert_embed = discord.Embed(
                    title="🚨 BOT ALERT",
                    description=f"**User {message.author.name}** has been banned and reported to law enforcement for violating Terms of Service.",
                    color=discord.Color.red()
                )
            alert_embed.add_field(
                name="🎯 Reason", 
                value="Presenting an immediate danger to the safety of children.",
                inline=False
            )
            
        await mod_channel.send(embed=alert_embed)
        

    async def send_ml_analysis_to_mod_channel(self, mod_channel, message, ml_prediction, risk_assessment, context):
        
        embed = discord.Embed(
            title="🤖 AI Message Analysis",
            description=f"**User:** {message.author.name} ({message.author.id})\n**Channel:** {message.channel.name}",
            color=self.get_embed_color(ml_prediction, risk_assessment),
            timestamp=datetime.now()
        )
        
        embed.add_field(
            name="📝 Message Content",
            value=f"```{message.content[:1000] if message.content else '*(No content)*'}```",
            inline=False
        )
        
        if ml_prediction and "error" not in ml_prediction:
            confidence_pct = ml_prediction['confidence'] * 100
            grooming_prob_pct = ml_prediction['grooming_probability'] * 100
            
            prediction_text = f"**Grooming Probability:** {grooming_prob_pct:.1f}%\n"
            prediction_text += f"**Model Confidence:** {confidence_pct:.1f}%\n"
            prediction_text += f"**Classification:** {'⚠️ Potential Grooming' if ml_prediction['is_grooming'] else '✅ Likely Safe'}"
            
            if ml_prediction.get('filter_reason'):
                prediction_text += f"\n**Note:** {ml_prediction['filter_reason'][:150]}"
            
            embed.add_field(
                name="🎯 ML Prediction",
                value=prediction_text,
                inline=True
            )
        elif ml_prediction and "error" in ml_prediction:
            embed.add_field(
                name="🎯 ML Prediction",
                value=f"❌ Error: {ml_prediction['error'][:100]}",
                inline=True
            )
        
        if risk_assessment:
            risk_text = f"**Risk Level:** {risk_assessment['risk_level'].title()}\n"
            risk_text += f"**Risk Score:** {risk_assessment['risk_score']:.1f}/100\n"
            risk_text += f"**Messages:** {risk_assessment['total_messages']} total, {risk_assessment['flagged_messages']} flagged\n"
            
            if risk_assessment['should_escalate']:
                risk_text += f"\n🚨 **ESCALATION:** {risk_assessment['escalation_reason']}"
            
            embed.add_field(
                name="📊 User Risk Profile",
                value=risk_text,
                inline=True
            )
        
        conversation_preview = self.classifier.format_conversation_for_prediction(context)
        embed.add_field(
            name="🔍 Analyzed Conversation",
            value=f"```{conversation_preview[:200]}...```",
            inline=False
        )
        
        await mod_channel.send(embed=embed)

    def get_embed_color(self, ml_prediction, risk_assessment):
        if risk_assessment and risk_assessment['should_escalate']:
            return discord.Color.red()
        elif ml_prediction and ml_prediction.get('grooming_probability', 0) > 0.8 and ml_prediction.get('confidence', 0) > 0.8:
            return discord.Color.orange()
        elif risk_assessment and risk_assessment['risk_level'] in ['critical', 'high']:
            return discord.Color.yellow()
        elif ml_prediction and ml_prediction.get('grooming_probability', 0) > 0.6:
            return discord.Color.gold()
        else:
            return discord.Color.green()

    async def auto_escalate_user(self, message, ml_prediction, risk_assessment):
        """Automatically escalate high-risk users"""
        try:
            grooming_prob = ml_prediction.get('grooming_probability', 0) if ml_prediction else 0
            confidence = ml_prediction.get('confidence', 0) if ml_prediction else 0
            
            report_data = {
                "reporter_id": self.user.id,  
                "reported_user_id": message.author.id,
                "message": message,
                "reason": "🤖 Automatic AI Detection",
                "details": f"**AI Risk Assessment:** {risk_assessment['escalation_reason']}\n"
                          f"**Grooming Probability:** {grooming_prob*100:.1f}%\n"
                          f"**Model Confidence:** {confidence*100:.1f}%\n"
                          f"**User Risk Score:** {risk_assessment['risk_score']:.1f}/100\n"
                          f"**Risk Level:** {risk_assessment['risk_level'].title()}",
                "score": max(10, 100 - risk_assessment['risk_score']),  # Lower score = higher concern
                "ml_prediction": ml_prediction
            }
            
            self.add_report_to_queue(report_data)
            
            mod_channel = self.mod_channels[message.guild.id]
            alert_embed = discord.Embed(
                title="🚨 AUTOMATIC AI ESCALATION",
                description=f"**User {message.author.name}** has been automatically flagged for review",
                color=discord.Color.red()
            )
            alert_embed.add_field(
                name="🎯 Reason", 
                value=risk_assessment['escalation_reason'], 
                inline=False
            )
            alert_embed.add_field(
                name="📊 Risk Score", 
                value=f"{risk_assessment['risk_score']:.1f}/100 ({risk_assessment['risk_level'].title()})", 
                inline=True
            )
            alert_embed.add_field(
                name="🤖 AI Confidence", 
                value=f"{grooming_prob*100:.1f}% grooming probability", 
                inline=True
            )
            alert_embed.add_field(
                name="⚡ Next Steps", 
                value="Use `!queue` to review pending reports", 
                inline=False
            )
            
            await mod_channel.send(embed=alert_embed)
            
        except Exception as e:
            logging.error(f"Error in auto-escalation: {e}")

    ### Everything Below These Lines are Relevant to Manual Reporting ###
    async def handle_mod_command(self, message):
        content = message.content.strip().lower()
        
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
        elif content.startswith('!profile'):
            await self.show_user_profile(message.channel, content)
        elif content == '!export':
            await self.export_data(message.channel)
        elif content == '!save':
            await self.save_data(message.channel)
        elif content.startswith('!help'):
            await self.show_mod_help(message.channel)

    async def export_data(self, channel):
        try:
            self.save_user_profiles()
            self.export_flagged_users_report()
            await channel.send("📁 **Data exported successfully!** Check the bot directory for files:\n"
                             f"• `flagged_conversations_{datetime.now().strftime('%Y%m%d')}.csv` - Daily flagged messages\n"
                             f"• `user_risk_profiles_[timestamp].json` - Complete user data\n"
                             f"• `flagged_users_report_[timestamp].csv` - Summary of high-risk users")
        except Exception as e:
            await channel.send(f"❌ Export failed: {e}")

    async def save_data(self, channel):
        try:
            self.save_user_profiles()
            await channel.send("💾 User profiles saved successfully!")
        except Exception as e:
            await channel.send(f"❌ Save failed: {e}")
    
    async def show_user_profile(self, channel, content):
        parts = content.split()
        if len(parts) < 2:
            await channel.send("Please specify a user ID: `!profile [user_id]`")
            return
        
        try:
            user_id = int(parts[1])
        except ValueError:
            await channel.send("Invalid user ID. Please provide a numeric user ID.")
            return
        
        if not self.risk_profiles or user_id not in self.risk_profiles.user_profiles:
            await channel.send(f"No profile data found for user ID: {user_id}")
            return
        
        profile = self.risk_profiles.user_profiles[user_id]
        risk_level, risk_score = self.risk_profiles.get_user_risk_level(user_id)
        should_escalate, escalation_reason = self.risk_profiles.should_escalate(user_id)
        
        try:
            user = await self.fetch_user(user_id)
            user_name = user.name
        except:
            user_name = "Unknown User"
        
        embed = discord.Embed(
            title=f"👤 User Profile: {user_name}",
            description=f"User ID: {user_id}",
            color=discord.Color.red() if should_escalate else discord.Color.blue()
        )
        
        embed.add_field(
            name="📊 Statistics",
            value=f"**Total Messages:** {profile['total_messages']}\n"
                  f"**Flagged Messages:** {profile['flagged_messages']}\n"
                  f"**Last Updated:** {profile['last_updated'].strftime('%Y-%m-%d %H:%M')}",
            inline=True
        )
        

        embed.add_field(
            name="⚠️ Risk Assessment",
            value=f"**Current Score:** {risk_score:.1f}/100\n"
                  f"**Risk Level:** {risk_level.title()}\n"
                  f"**Highest Score:** {profile['highest_risk_score']:.1f}",
            inline=True
        )
        
        if profile['predictions_history']:
            recent = profile['predictions_history'][-5:]  
            recent_text = ""
            for i, pred in enumerate(recent):
                recent_text += f"{i+1}. {pred['grooming_probability']*100:.1f}% (conf: {pred['confidence']*100:.1f}%)\n"
            
            embed.add_field(
                name="🔮 Recent Predictions",
                value=recent_text or "No recent predictions",
                inline=False
            )
        
        if should_escalate:
            embed.add_field(
                name="🚨 Escalation Status",
                value=f"**REQUIRES ESCALATION**\n{escalation_reason}",
                inline=False
            )
        
        await channel.send(embed=embed)
    

    async def show_report_queue(self, channel):
        """Show a list of pending reports"""
        if not self.mod_reports:
            await channel.send("No reports in the queue.")
            return
        
        pending_reports = [r for r in self.mod_reports if r.status == "pending"]
        if not pending_reports:
            await channel.send("No pending reports in the queue.")
            return
        
        embed = discord.Embed(title="📋 Report Queue", color=discord.Color.blue())
        for i, report in enumerate(pending_reports):
            ai_indicator = "🤖 " if report.ml_prediction else ""
            embed.add_field(
                name=f"Report #{i+1}: {ai_indicator}{report.reason}", 
                value=f"From: <@{report.reporter_id}> | Against: <@{report.reported_user_id}> | Score: {report.score}",
                inline=False
            )
        await channel.send(embed=embed)

    async def show_next_report(self, channel):
        """Show the next report in the queue"""
        if not self.mod_reports:
            await channel.send("No reports in the queue.")
            return
        
        for _ in range(len(self.mod_reports)):
            self.current_report_index = (self.current_report_index + 1) % len(self.mod_reports)
            if self.mod_reports[self.current_report_index].status == "pending":
                break
        else:
            await channel.send("No pending reports in the queue.")
            return
        
        report = self.mod_reports[self.current_report_index]
        
        embed = discord.Embed(
            title=f"📋 Report: {report.reason}",
            description=f"**Score:** {report.score}/100",
            color=discord.Color.red() if report.score < 30 else discord.Color.orange()
        )
        embed.add_field(name="👤 Reporter", value=f"<@{report.reporter_id}>", inline=True)
        embed.add_field(name="⚠️ Reported User", value=f"<@{report.reported_user_id}>", inline=True)
        embed.add_field(name="📝 Details", value=report.details[:1000], inline=False)
        
        if report.ml_prediction:
            ml_info = f"**Grooming Probability:** {report.ml_prediction['grooming_probability']*100:.1f}%\n"
            ml_info += f"**Model Confidence:** {report.ml_prediction['confidence']*100:.1f}%"
            embed.add_field(name="🤖 AI Analysis", value=ml_info, inline=True)
        
        embed.add_field(name="📊 Status", value=report.status, inline=True)
        embed.add_field(name="⚡ Options", value="Use `!view thread` to see the full message thread\n"
                                         "Use `!view message` to see the reported message\n"
                                         "Use `!search [keywords]` to search for keywords\n"
                                         "Use `!profile [user_id]` to see user profile\n"
                                         "Use `!action [type]` to take action", inline=False)
        await channel.send(embed=embed)

    async def view_report_details(self, channel, content):
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
            
            embed = discord.Embed(title="💬 Message Thread", description=f"Channel: {text_channel.name}", color=discord.Color.blue())
            for msg in messages:
                name_prefix = "⚠️ " if msg.id == message.id else ""
                embed.add_field(
                    name=f"{name_prefix}{msg.author.name} ({msg.created_at.strftime('%Y-%m-%d %H:%M')})",
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
            title="⚠️ Reported Message",
            description=f"From: {message.author.name}",
            color=discord.Color.red()
        )
        embed.add_field(name="Content", value=message.content[:1024] if message.content else "(No content)", inline=False)
        embed.add_field(name="Sent At", value=message.created_at.strftime("%Y-%m-%d %H:%M"), inline=True)
        embed.add_field(name="Channel", value=message.channel.name, inline=True)
        
        if report.ml_prediction:
            ml_text = f"Grooming Probability: {report.ml_prediction['grooming_probability']*100:.1f}%\n"
            ml_text += f"Model Confidence: {report.ml_prediction['confidence']*100:.1f}%"
            embed.add_field(name="🤖 AI Analysis", value=ml_text, inline=False)
        
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
        
        try:
            messages = []
            async for msg in text_channel.history(limit=100, around=message):
                messages.append(msg)

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
                title=f"🔍 Messages Containing Keywords", 
                description=f"Found {len(matching_messages)} messages with keywords: {', '.join(keywords)}",
                color=discord.Color.gold()
            )
            
            for i, msg in enumerate(matching_messages[:10]): 
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
            await channel.send("Please specify an action: `!action [ban|suspend|increase|report|none|skip]`")
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
        elif action_type == "increase":
            if len(parts) < 3:
                await channel.send("Please specify new score: `!action increase [new_score]`")
                return
            try:
                new_score = int(parts[2])
                await self.increase_user_score(channel, report, new_score)
            except ValueError:
                await channel.send("Invalid score. Please use a number.")
        elif action_type == "report":
            await self.report_to_law(channel, report)
        elif action_type == "none":
            report.status = "completed"
            report.mod_actions.append(ModAction.NO_ACTION)
            await channel.send("No action taken. Report marked as complete.")
        elif action_type == "skip":
            await channel.send("Report skipped. Use `!next` to move to the next report.")
        else:
            await channel.send("Unknown action type. Use `ban`, `suspend`, `increase`, `report`, `none`, or `skip`.")

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
            
            moderator = channel.last_message.author
        
            confirm_msg = await channel.send(f"Are you sure you want to ban {member.name}? React with ✅ to confirm or ❌ to cancel.")
            await confirm_msg.add_reaction("✅")
            await confirm_msg.add_reaction("❌")
            
            def check(reaction, user):
                return user == moderator and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
            
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
            
            until = discord.utils.utcnow() + timedelta(days=days)
            await member.timeout(until, reason=f"Timed out for {report.reason}")
            
            report.status = "completed"
            report.mod_actions.append(ModAction.SUSPEND_ACCOUNT)
            await channel.send(f"User {member.name} has been suspended for {days} days (until {until.strftime('%Y-%m-%d %H:%M UTC')}).")
        except Exception as e:
            await channel.send(f"Error suspending user: {str(e)}")

    async def increase_user_score(self, channel, report, new_score):
        """Increase a user's risk score"""
        if new_score < 0 or new_score > 100:
            await channel.send("Score must be between 0 and 100.")
            return
        self.user_scores[report.reported_user_id] = new_score
        
        if self.risk_profiles and report.reported_user_id in self.risk_profiles.user_profiles:
            self.risk_profiles.user_profiles[report.reported_user_id]['risk_score'] = 100 - new_score
        
        report.status = "completed"
        report.mod_actions.append(ModAction.INCREASE_SCORE)
        await channel.send(f"User's risk score has been updated to {new_score}.")

    async def report_to_law(self, channel, report):
        """Simulate reporting to law enforcement"""
        moderator = channel.last_message.author
        confirm_msg = await channel.send(f"Are you sure you want to report this to law enforcement? React with ✅ to confirm or ❌ to cancel.")
        await confirm_msg.add_reaction("✅")
        await confirm_msg.add_reaction("❌")
        
        def check(reaction, user):
            return user == moderator and str(reaction.emoji) in ["✅", "❌"] and reaction.message.id == confirm_msg.id
        
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
        embed = discord.Embed(title="🔧 Moderator Commands Help", color=discord.Color.blue())
        embed.add_field(name="!queue", value="Show pending reports in the queue", inline=False)
        embed.add_field(name="!next", value="View the next report in the queue", inline=False)
        embed.add_field(name="!view thread", value="View the full message thread around the reported message", inline=False)
        embed.add_field(name="!view message", value="View just the reported message", inline=False)
        embed.add_field(name="!search [keywords]", value="Search for messages with keywords", inline=False)
        embed.add_field(name="!profile [user_id]", value="Show detailed user risk profile", inline=False)
        embed.add_field(name="!export", value="Export all flagged data to CSV/JSON files", inline=False)
        embed.add_field(name="!save", value="Save current user profiles to file", inline=False)
        embed.add_field(name="!action ban", value="Ban the reported user", inline=False)
        embed.add_field(name="!action suspend [days]", value="Suspend the user for specified days", inline=False)
        embed.add_field(name="!action increase [score]", value="Set a new risk score for the user", inline=False)
        embed.add_field(name="!action report", value="Report to law enforcement", inline=False)
        embed.add_field(name="!action none", value="Take no action and mark report as complete", inline=False)
        embed.add_field(name="!action skip", value="Skip this report for now", inline=False)
        embed.add_field(name="!help", value="Show this help message", inline=False)
        
        embed.set_footer(text="🤖 Pure ML Detection Active - No Rule-Based Filtering")
        
        await channel.send(embed=embed)

    def add_report_to_queue(self, report_data):
        """Add a report to the moderation queue from report data"""
        new_report = ModReport(
            reporter_id=report_data["reporter_id"],
            reported_user_id=report_data["reported_user_id"],
            message=report_data["message"],
            reason=report_data["reason"],
            details=report_data["details"],
            score=report_data["score"],
            ml_prediction=report_data.get("ml_prediction")
        )
        self.mod_reports.append(new_report)


client = ModBot()
client.run(discord_token)