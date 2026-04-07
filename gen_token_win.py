from google_auth_oauthlib.flow import InstalledAppFlow
import json
flow = InstalledAppFlow.from_client_secrets_file('gmail_credentials.json', scopes=['https://www.googleapis.com/auth/gmail.modify'])
creds = flow.run_local_server(port=8091)
json.dump({'token': creds.token, 'refresh_token': creds.refresh_token, 'token_uri': creds.token_uri, 'client_id': creds.client_id, 'client_secret': creds.client_secret, 'scopes': list(creds.scopes)}, open('gmail_token.json','w'), indent=2)
print('Token generado OK')
