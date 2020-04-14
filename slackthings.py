import os
import slack

client = slack.WebClient(token="-------------------")

def slack_msg_to_prance_general(message):
    client.chat_postMessage(channel="---------", text=message)
