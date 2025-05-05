from enum import Enum, auto
import discord
import re

class State(Enum):
    REPORT_START = auto()
    AWAITING_MESSAGE = auto()
    MESSAGE_IDENTIFIED = auto()
    REPORT_COMPLETE = auto()
    NARROWING_DOWN_GROOMING = auto()
    ADDITIONAL_INFO = auto()
    POTENTIALLY_MORE_INFO = auto()
    BLOCK = auto()
    FINISH_REPORT = auto()

class Report:
    START_KEYWORD = "report"
    CANCEL_KEYWORD = "cancel"
    HELP_KEYWORD = "help"

    def __init__(self, client):
        self.state = State.REPORT_START
        self.client = client
        self.message = None
    
    async def handle_message(self, message):
        '''
        This function makes up the meat of the user-side reporting flow. It defines how we transition between states and what 
        prompts to offer at each of those states. You're welcome to change anything you want; this skeleton is just here to
        get you started and give you a model for working with Discord. 
        '''

        if message.content == self.CANCEL_KEYWORD:
            self.state = State.REPORT_COMPLETE
            return ["Report complete."]
        
        if self.state == State.REPORT_START:
            reply =  "Thank you for starting the reporting process. "
            reply += "Say `help` at any time for more information.\n\n"
            reply += "Please copy paste the link to the message you want to report.\n"
            reply += "You can obtain this link by right-clicking the message and clicking `Copy Message Link`."
            self.state = State.AWAITING_MESSAGE
            return [reply]
        
        if self.state == State.AWAITING_MESSAGE:
            # Parse out the three ID strings from the message link
            m = re.search('/(\d+)/(\d+)/(\d+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read that link. Please try again or say `cancel` to cancel."]
            guild = self.client.get_guild(int(m.group(1)))
            if not guild:
                return ["I cannot accept reports of messages from guilds that I'm not in. Please have the guild owner add me to the guild and try again."]
            channel = guild.get_channel(int(m.group(2)))
            if not channel:
                return ["It seems this channel was deleted or never existed. Please try again or say `cancel` to cancel."]
            try:
                message = await channel.fetch_message(int(m.group(3)))
            except discord.errors.NotFound:
                return ["It seems this message was deleted or never existed. Please try again or say `cancel` to cancel."]

            reply = "I found this message:" + "```" + message.author.name + ": " + message.content + "```\n"
            reply += "What would you like to report? Enter the number of the option you want to select.\n"
            reply += "1. Harassment\n"
            reply += "2. Spam\n"
            reply += "3. Child safety concern\n"
            reply += "4. Other\n"
            self.state = State.NARROWING_DOWN_GROOMING
            return [reply]
        
        if self.state == State.NARROWING_DOWN_GROOMING:
            if "3" in message.content:
                self.state = State.ADDITIONAL_INFO
                reply = "What kind of child safety concern? Enter the number of the option you want to select.\n"
                reply += "1. Suspected grooming\n"
                reply += "2. Sharing inappropriate images\n"
                reply += "3. Attempts to meet in person\n"
                reply += "4. Other"
                return [reply]
            else:
                self.state = State.REPORT_COMPLETE
                return ["We have not yet built support for options 1, 2, and 4."]
            
        if self.state == State.ADDITIONAL_INFO:
            self.state = State.POTENTIALLY_MORE_INFO
            reply = "Can you tell us more about what happened? Enter the number of the option you want to select.\n"
            reply += "1. They are impersonating someone else's identity.\n"
            reply += "2. They tried to isolate me from others.\n"
            reply += "3. They asked for private conversations off this app.\n"
            reply += "4. They pressured me for sensitive photos.\n"
            reply += "5. They tried to meet up in person.\n"
            reply += "6. Other"
            return [reply]
        
        if self.state == State.POTENTIALLY_MORE_INFO:
            reply = "Is there any additional information you would like to provide? If not, say `no`."
            self.state = State.BLOCK
            return [reply]
        
        if self.state == State.BLOCK:
            reply = "Would you like to block this user now? Enter 'yes' or 'no'."
            self.state = State.FINISH_REPORT
            return [reply]
        
        if self.state == State.FINISH_REPORT:  
            reply = ""
            if message.content.lower().strip() == "yes":
                reply = "You have blocked this user.\n\n"       
            reply += "Thank you for your report. We will review it and take appropriate action. No further information is requested from you at this time."
            self.state = State.REPORT_COMPLETE
            return [reply]

        return []

    def report_complete(self):
        return self.state == State.REPORT_COMPLETE
    


    

