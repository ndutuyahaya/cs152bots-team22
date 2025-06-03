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
        self.concern_type = None
        self.additional_info = None
    
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
            reply += "Say 'help' at any time for more information.\n\n"
            reply += "Please copy paste the link to the message you want to report.\n"
            reply += "You can obtain this link by right-clicking the message and clicking 'Copy Message Link'."
            self.state = State.AWAITING_MESSAGE
            return [reply]
        
        if self.state == State.AWAITING_MESSAGE:
            m = re.search('/(\d+)/(\d+)/(\d+)', message.content)
            if not m:
                return ["I'm sorry, I couldn't read that link. Please try again or say 'cancel' to cancel."]
            guild = self.client.get_guild(int(m.group(1)))
            if not guild:
                return ["I cannot accept reports of messages from guilds that I'm not in. Please have the guild owner add me to the guild and try again."]
            channel = guild.get_channel(int(m.group(2)))
            if not channel:
                return ["It seems this channel was deleted or never existed. Please try again or say 'cancel' to cancel."]
            try:
                self.message = await channel.fetch_message(int(m.group(3)))
            except discord.errors.NotFound:
                return ["It seems this message was deleted or never existed. Please try again or say 'cancel' to cancel."]

            reply = "I found this message: " + "\"" + self.message.author.name + ": " + self.message.content + "\"\n"
            reply += "What would you like to report? Enter the number of the option you want to select.\n"
            reply += "1. Harassment\n"
            reply += "2. Suicide or self-injury\n"
            reply += "3. Violence or dangerous organizations\n"
            reply += "4. Nudity or sexual activity\n"
            reply += "5. Selling or promoting restricted items\n"
            reply += "6. Scam or fraud\n"
            reply += "7. Other\n"
            self.state = State.NARROWING_DOWN_GROOMING
            return [reply]
        
        if self.state == State.NARROWING_DOWN_GROOMING:
            if "4" in message.content:
                self.state = State.ADDITIONAL_INFO
                reply = "Which best describes this problem? Enter the number of the option you want to select.\n"
                reply += "1. Threatening to share nude images\n"
                reply += "2. Nudity or adult material\n"
                reply += "3. Sexual exploitation\n"
                reply += "4. Prostitution\n"
                reply += "5. Involves someone under 18\n"
                reply += "6. None of the above\n"
                return [reply]
            else:
                self.state = State.REPORT_COMPLETE
                return ["We have not yet built support for options other than option 4."]
            
        if self.state == State.ADDITIONAL_INFO:
            # Storing the concern type
            concern_types = ["Threatening to share nude images", "Nudity or adult material", "Sexual exploitation", "Prostitution", "Involves someone under 18", "None"]
            if message.content.isdigit() and 1 <= int(message.content) <= 6:
                self.concern_type = concern_types[int(message.content) - 1]
            else:
                self.concern_type = "Unspecified"
                
            self.state = State.POTENTIALLY_MORE_INFO
            reply = "Tell us more about what happened. Enter the number of the option you want to select.\n"
            reply += "1. They are impersonating someone else's identity.\n"
            reply += "2. They tried to isolate me from others.\n"
            reply += "3. They asked for private conversations off this app.\n"
            reply += "4. They pressured me for sensitive photos.\n"
            reply += "5. They tried to meet up in person.\n"
            reply += "6. None of the above"
            return [reply]
        
        if self.state == State.POTENTIALLY_MORE_INFO:
            # Storing the additional info
            additional_info_options = [
                "Impersonating someone's identity",
                "Trying to isolate from others",
                "Asked for private conversations off app",
                "Pressured for sensitive photos",
                "Tried to meet up in person",
                "None"
            ]
            if message.content.isdigit() and 1 <= int(message.content) <= 6:
                self.additional_info = additional_info_options[int(message.content) - 1]
            else:
                self.additional_info = message.content
                
            reply = "Enter any additional information you would like to provide. If you have nothing to add, say 'no'."
            self.state = State.BLOCK
            return [reply]
        
        if self.state == State.BLOCK:
            # Storing any extra information provided
            if message.content.lower() != "no":
                if self.additional_info:
                    self.additional_info += f" | Extra info: {message.content}"
                else:
                    self.additional_info = f"Extra info: {message.content}"
                
            reply = "Would you like to block this user now? Enter 'yes' or 'no'."
            self.state = State.FINISH_REPORT
            return [reply]
        
        if self.state == State.FINISH_REPORT:  
            reply = ""
            if message.content.lower().strip() == "yes":
                reply = "You have blocked this user.\n\n"       
            reply += "Thank you for your report. We will review it and take appropriate action. No further information is requested from you at this time."
         
            if hasattr(self, 'message') and self.message:
                report_data = {
                    "reporter_id": message.author.id,
                    "reported_user_id": self.message.author.id,
                    "message": self.message,
                    "reason": "Child Safety Concern",
                    "details": f"Specific concern: {self.concern_type if self.concern_type else 'Unknown'}. Additional info: {self.additional_info if self.additional_info else 'None'}",
                    "score": 30  # Starting score for child safety concerns is low
                }
                # Letting the client handle creating the report object
                self.client.add_report_to_queue(report_data)
            
            self.state = State.REPORT_COMPLETE
            return [reply]

        return []

    def report_complete(self):
        return self.state == State.REPORT_COMPLETE