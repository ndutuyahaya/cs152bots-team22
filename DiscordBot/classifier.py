import torch
import pandas as pd
from transformers import AutoTokenizer, AutoModelForSequenceClassification
import numpy as np
from datetime import datetime, timedelta
import asyncio
import logging

class GroomingClassifier:
    def __init__(self, model_path="models/grooming-detector-20250526_002419"):
       
        self.model_path = model_path
        self.tokenizer = None
        self.model = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        
        self.load_model()
        
    def load_model(self):
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            self.model = AutoModelForSequenceClassification.from_pretrained(self.model_path)
            self.model.to(self.device)
            self.model.eval()
            logging.info(f"Model loaded successfully from {self.model_path}")
        except Exception as e:
            logging.error(f"Error loading model: {e}")
            raise
    
    def format_conversation_for_prediction(self, messages):
       
        conversation_lines = []
        for msg in messages:
            author_name = msg.author.name if hasattr(msg.author, 'name') else str(msg.author.id)
            content = msg.content if msg.content else ""
            conversation_lines.append(f"{author_name}: {content}")
        
        return "\n".join(conversation_lines)
    
    def predict_grooming_probability(self, conversation_text):
      
        try:
            if not conversation_text or len(conversation_text.strip()) < 5:
                return {
                    "grooming_probability": 0.0,
                    "confidence": 0.95,
                    "predicted_class": 0,
                    "is_grooming": False,
                    "filter_reason": "Empty or too short conversation"
                }
            
            raw_prediction = self._get_raw_model_prediction(conversation_text)
            
            return {
                "grooming_probability": raw_prediction['grooming_probability'],
                "confidence": raw_prediction['confidence'],
                "predicted_class": raw_prediction['predicted_class'],
                "is_grooming": raw_prediction['is_grooming'],
                "filter_reason": "Pure ML prediction - no filtering applied"
            }
            
        except Exception as e:
            logging.error(f"Error in prediction: {e}")
            return {
                "grooming_probability": 0.0,
                "confidence": 0.0,
                "predicted_class": 0,
                "is_grooming": False,
                "error": str(e)
            }
    
    def _get_raw_model_prediction(self, conversation_text):
        inputs = self.tokenizer(
            conversation_text, 
            truncation=True, 
            padding="max_length", 
            max_length=512,
            return_tensors="pt"
        )
        
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        
        with torch.no_grad():
            outputs = self.model(**inputs)
            logits = outputs.logits
            
        probabilities = torch.softmax(logits, dim=-1)
        grooming_prob = probabilities[0][1].item() 
        confidence = torch.max(probabilities).item()
        predicted_class = torch.argmax(probabilities, dim=-1).item()
        
        return {
            "grooming_probability": grooming_prob,
            "confidence": confidence,
            "predicted_class": predicted_class,
            "is_grooming": predicted_class == 1,
            "raw_logits": logits.cpu().numpy().tolist()
        }
    
    # def debug_prediction(self, conversation_text):
    #     """Debug method to see model predictions"""
    #     print(f"\n=== DEBUG PREDICTION ===")
    #     print(f"Input conversation:\n{conversation_text}")
        
    #     # Get prediction
    #     prediction = self.predict_grooming_probability(conversation_text)
    #     print(f"Model prediction: {prediction['grooming_probability']*100:.1f}% (confidence: {prediction['confidence']*100:.1f}%)")
    #     print(f"Classification: {'⚠️ Potential Grooming' if prediction['is_grooming'] else '✅ Likely Safe'}")
    #     print(f"Filter reason: {prediction.get('filter_reason', 'None')}")
    #     print("========================\n")
        
    #     return prediction

class ConversationBuffer:
    """
    Manages conversation history for users to build context for predictions
    """
    def __init__(self, max_messages=50, time_window_hours=24):
        self.user_conversations = {}  
        self.max_messages = max_messages
        self.time_window = timedelta(hours=time_window_hours)
    
    def add_message(self, user_id, message):
        """Add a message to user's conversation buffer"""
        if user_id not in self.user_conversations:
            self.user_conversations[user_id] = []
        
        self.user_conversations[user_id].append({
            'message': message,
            'timestamp': datetime.now()
        })
        
        self._clean_old_messages(user_id)
    
    def _clean_old_messages(self, user_id):
        """Remove messages older than time window and limit to max_messages"""
        if user_id not in self.user_conversations:
            return
        
        now = datetime.now()
        messages = self.user_conversations[user_id]
        
        messages = [
            msg for msg in messages 
            if now - msg['timestamp'] <= self.time_window
        ]
        
        if len(messages) > self.max_messages:
            messages = messages[-self.max_messages:]
        
        self.user_conversations[user_id] = messages
    
    def get_conversation_context(self, user_id, include_recent=10):
        """Get recent conversation context for a user"""
        if user_id not in self.user_conversations:
            return []
        
        messages = self.user_conversations[user_id]
        return [msg['message'] for msg in messages[-include_recent:]]

class UserRiskProfile:
    """
    Manages user risk profiles based on conversation analysis
    """
    def __init__(self, grooming_threshold=0.7, confidence_threshold=0.8):
        self.user_profiles = {}  
        self.grooming_threshold = grooming_threshold
        self.confidence_threshold = confidence_threshold
    
    def update_user_score(self, user_id, prediction_result, message_context=None):
        """
        Update user's risk profile based on ML predictions
        
        Args:
            user_id: Discord user ID
            prediction_result: Result from GroomingClassifier.predict_grooming_probability
            message_context: Additional context about the message
        """
        if user_id not in self.user_profiles:
            self.user_profiles[user_id] = {
                'risk_score': 50,  
                'total_messages': 0,
                'flagged_messages': 0,
                'predictions_history': [],
                'last_updated': datetime.now(),
                'highest_risk_score': 50
            }
        
        profile = self.user_profiles[user_id]
        profile['total_messages'] += 1
        profile['last_updated'] = datetime.now()
        
        prediction_entry = {
            'timestamp': datetime.now(),
            'grooming_probability': prediction_result['grooming_probability'],
            'confidence': prediction_result['confidence'],
            'predicted_class': prediction_result['predicted_class']
        }
        profile['predictions_history'].append(prediction_entry)

        if len(profile['predictions_history']) > 100:
            profile['predictions_history'] = profile['predictions_history'][-100:]

        grooming_prob = prediction_result['grooming_probability']
        confidence = prediction_result['confidence']
        
        if grooming_prob > self.grooming_threshold and confidence > self.confidence_threshold:
            profile['flagged_messages'] += 1
        

        recent_predictions = profile['predictions_history'][-10:]  
        
        if recent_predictions:
            weighted_scores = []
            for pred in recent_predictions:
                if pred['confidence'] > self.confidence_threshold:
                    weight = pred['confidence']
                    weighted_score = pred['grooming_probability'] * weight
                    weighted_scores.append(weighted_score)
            
            if weighted_scores:
                avg_weighted_score = sum(weighted_scores) / len(weighted_scores)
                new_component = avg_weighted_score * 100
                
                profile['risk_score'] = (profile['risk_score'] * 0.7) + (new_component * 0.3)
        
        profile['highest_risk_score'] = max(
            profile['highest_risk_score'], 
            profile['risk_score']
        )
        
        return profile
    
    def get_user_risk_level(self, user_id):
        """Get user's current risk level"""
        if user_id not in self.user_profiles:
            return "unknown", 50
        
        score = self.user_profiles[user_id]['risk_score']
        
        if score >= 90:
            return "critical", score
        elif score >= 75:
            return "high", score
        elif score >= 60:
            return "medium", score
        elif score >= 40:
            return "low", score
        else:
            return "minimal", score
    
    def should_escalate(self, user_id):
        """Determine if user should be escalated based on ML predictions"""
        if user_id not in self.user_profiles:
            return False, "No profile data"
        
        profile = self.user_profiles[user_id]
        
        if profile['risk_score'] >= 90:
            return True, f"Critical risk score: {profile['risk_score']:.1f}"
        
        high_confidence_flags = sum(
            1 for pred in profile['predictions_history'][-10:]
            if pred['grooming_probability'] > self.grooming_threshold and pred['confidence'] > self.confidence_threshold
        )
        if high_confidence_flags >= 3:
            return True, f"Multiple high-confidence flags: {high_confidence_flags}"
        
        if len(profile['predictions_history']) >= 5:
            recent_high = [
                pred for pred in profile['predictions_history'][-5:]
                if pred['grooming_probability'] > self.grooming_threshold and pred['confidence'] > self.confidence_threshold
            ]
            if len(recent_high) >= 3: 
                avg_risk = sum(pred['grooming_probability'] for pred in recent_high) / len(recent_high)
                return True, f"Consistent high-risk behavior: {avg_risk:.2f} avg"
        
        return False, "No escalation needed"