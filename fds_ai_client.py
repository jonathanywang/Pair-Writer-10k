import os
import streamlit as st
from openai import AzureOpenAI, Stream
from dotenv import load_dotenv, find_dotenv

# Load env variables
load_dotenv(find_dotenv())
os.environ["SSL_CERT_FILE"] = os.getenv("REQUESTS_CA_BUNDLE")


class FDSAIClient:
    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL")
        self.client = AzureOpenAI(
            api_version=os.getenv("OPENAI_API_VERSION"),
            azure_endpoint=os.getenv("OPENAI_API_BASE_URL"),
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        
    def create(self, messages, system_prompt = "", stream = True):
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        stream = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": m["role"], "content": m["content"]}
                for m in messages
            ],
            stream=stream
        )
        return stream
