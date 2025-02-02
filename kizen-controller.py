import requests
import uuid
import os
from datetime import datetime, timedelta
import json
from dotenv import load_dotenv
import boto3

load_dotenv()

class KizenClient:
    def __init__(self):
        self.base_url = os.getenv('KIZEN_API_URL')
        self.api_key = os.getenv('KIZEN_API_KEY')
        self.user_id = os.getenv('KIZEN_USER_ID')
        self.business_id = os.getenv('KIZEN_BUSINESS_ID')
        self.headers = {
            'X-API-Key': self.api_key,
            'X-User-Id': self.user_id,
            'X-Business-Id': self.business_id,
            'CONTENT-TYPE': 'application/json'            
        }
    def check_connection(self):
        """Check API connection using a simple POST request"""
        url = f"{self.base_url}/client/v2"  # Using standard client endpoint
        params = {
            'page_size': 50,
            'page': 1
        }
        
        try:
            response = requests.post(url, headers=self.headers, json=params)
            
            if response.status_code == 200:
                print("Connection successful! API response:")
                print(response.json())
                return True
            else:
                print(f"Connection failed with status code: {response.status_code}")
                print(f"Error response: {response.text}")
                return False
                
        except requests.RequestException as e:
            print(f"Connection error: {str(e)}")
            return False
        
    def _get_s3_signature(self, file_name, content_type, environment, access_key=None):
            """Get S3 upload signature from Kizen"""

            expiration = (datetime.now() + timedelta(minutes=5)).isoformat() + 'Z'
            file_ext = file_name.split('.')[-1]
            file_key = f"{uuid.uuid4()}.{file_ext}"

            print(f"File name: {file_name}")
            print(f"File key: {file_key}")
            print(f"File extension : {file_ext}")

            print(f"Access key: {access_key}")
            aws_access_key = access_key


            
            # Determine bucket based on environment
            bucket, region = self._get_s3_bucket(environment)
            # Add proper Content-Type header
            headers = self.headers.copy()
            headers['Content-Type'] = 'application/json'        
            
            signature_data = {
                "expiration": expiration,
                "conditions": [
                    {"acl": "private"},
                    {"bucket": bucket},
                    ["starts-with", "$key", ""],
                    {"content-type": content_type},
                    {"success_action_status": "200"},
                    {"key": file_key},
                    {"x-amz-meta-qqfilename": file_name},
                    {"x-amz-algorithm": "AWS4-HMAC-SHA256"},
                    {"x-amz-credential": f"{aws_access_key}/{datetime.now().strftime('%Y%m%d')}/{region}/s3/aws4_request"},
                    {"x-amz-date": datetime.now().strftime('%Y%m%dT%H%M%SZ')},
                    ["content-length-range", "0", "50000000"]
                ]
            }
            try:                        
                response = requests.post(
                    f"{self.base_url}/s3/signature",
                    json=signature_data,
                    headers=headers
                )
                response.raise_for_status()
                return response.json(), file_key 
            except requests.exceptions.HTTPError as e:
                print(f"Signature request failed: {e.response.text}")
                raise    

    def _get_s3_bucket(self, environment):
        """Get S3 bucket configuration based on environment"""
        if environment == 'staging':
            return 'staging-file-cdn', 'us-east-1'
        elif environment == 'go':
            return 'kizen-file-cdn', 'us-east-1'
        elif environment == 'fmo':
            return 'fmo-file-cdn', 'us-east-2'
        elif environment == 'testing':
            return 'sfdc-data-cloud', 'us-east-1'
        raise ValueError(f"Unsupported environment: {environment}")

    def upload_file(self, file_path, content_type, environment, access_key=None):
        """Upload file to S3 and register with Kizen"""
        file_name = os.path.basename(file_path)
        
        # Get S3 signature from Kizen
        signature_data, file_key = self._get_s3_signature(file_name, content_type, environment, access_key)
        print(f"Signature data: {signature_data}")
        bucket, region = self._get_s3_bucket(environment)
        print(f"Bucket: {bucket}, Region: {region}")
        
        # Upload to S3
        s3_url = f"https://{bucket}.s3.amazonaws.com/"
        with open(file_path, 'rb') as f:
            files = {
                'file': (file_name, f, content_type)
            }
            data = {
                'key': file_key,
                'content-type': content_type,
                'success_action_status': '200',
                'acl': 'private',
                'x-amz-meta-qqfilename': file_name,
                'policy': signature_data['policy'],
                'x-amz-algorithm': 'AWS4-HMAC-SHA256',
                'x-amz-credential': signature_data['x-amz-credential'],
                'x-amz-date': signature_data['x-amz-date'],
                'x-amz-signature': signature_data['signature']
            }
            s3_response = requests.post(s3_url, files=files, data=data)
            s3_response.raise_for_status()
        
        # Register with Kizen
        success_payload = {
            'key': file_key,
            'uuid': file_key.split('.')[0],
            'name': file_name,
            'bucket': bucket,
            'etag': s3_response.headers.get('ETag', ''),
            'is_public': 'False'
        }
        success_response = requests.post(
            f"{self.base_url}/s3/success",
            data=success_payload,
            headers=self.headers
        )
        success_response.raise_for_status()
        print(f"Success response: {success_response.json()}")
        print(success_response.json()['id'])
        
        return {
            'id': success_response.json()['id'],
            'url': f"https://{bucket}.s3.amazonaws.com/{file_key}",
            'size_bytes': os.path.getsize(file_path)
        }           
        
    def update_phone_call(self, client_object_identifier, client_update_record_id, file_url):
        """Update phone call record with recording details"""

        update_url = f"{self.base_url}/records/{client_object_identifier}/{client_update_record_id}"
        # create a file object and store 2860517494016.mp3
        file = open('2860517494016.mp3', 'rb')

        # update_url = f"{self.base_url}/records/phone_call/{phone_call_id}"
        update_payload = json.dumps(
            {
                "fields": [
                    {
                        "name": "call_recording_link",
                        "value": file_url
                    },
                    # {
                    #     "name": "call_recording",
                    #     "value": file
                    # }
                ]
            }
        )
        # response = requests.put(update_url, json=payload, headers=self.headers)
        update_response = requests.request("PUT", update_url, headers=self.headers, data=update_payload)
        update_response.raise_for_status()
        return update_response.json()        

# Usage Example
if __name__ == "__main__":
    ## Login to Kizen API
    kizen = KizenClient()
    print(f"Attempting connection to: {kizen.base_url}")
    ## Check connection to the book of buisness
    if kizen.check_connection():
        print("Successfully connected to Kizen API")
    else:
        print("Failed to establish connection to Kizen API")


    ## Upload a file to S3 and register with Kizen
    file_recording = '2860517494016.mp3'
    #first check if the file_recording exists
    if os.path.exists(file_recording):
        # check the signature first _get_s3_signature
        try:
            access_key = os.getenv('AWS_KIZEN_ACCESS_KEY_ID')
            upload_response = kizen.upload_file(file_recording, 'audio/mpeg', 'fmo', access_key)
            print(f"Upload response: {upload_response}")

            client_object_identifier='02a2c75d-6393-4ac7-835c-bff4a3d04b13'
            client_update_record_id='e65e2a12-d8eb-4fde-a126-7c8db5ab79fa'        
            update_response = kizen.update_phone_call(
                        client_object_identifier, 
                        client_update_record_id, 
                        upload_response['url']
            #             # upload_result['s3_key']
            #             # upload_response['url'],
            #             # upload_response['id']
                    )            
            # print the status of the update operation with a message
            print(f'Update operation status: {update_response}')            
        except Exception as e:
            print(f"Error getting S3 signature: {str(e)}")
            exit(1)

        
    else:
        print(f"File {file_recording} does not exist")
    
    
    


