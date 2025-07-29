# src/security/key_manager.py
import json
import os
import getpass
import base64
import secrets
import hashlib
from config import logger

class KeyManager:
    @staticmethod
    def derive_key(password: str, salt: bytes) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 100000, 32)

    @staticmethod
    def encrypt_data(data: dict, password: str) -> dict:
        salt = secrets.token_bytes(16)
        key = KeyManager.derive_key(password, salt)
        data_bytes = json.dumps(data).encode()
        length = len(data_bytes)
        length_bytes = length.to_bytes(4, 'big')
        to_pad = length_bytes + data_bytes
        block_size = len(key)
        pad_length = (block_size - (len(to_pad) % block_size)) % block_size
        padded_data = to_pad + b"\x00" * pad_length
        encrypted = bytes(a ^ b for a, b in zip(padded_data, key * (len(padded_data) // block_size)))
        return {"salt": base64.b64encode(salt).decode(), "encrypted": base64.b64encode(encrypted).decode()}

    @staticmethod
    def decrypt_data(encrypted_data: dict, password: str) -> dict:
        salt = base64.b64decode(encrypted_data["salt"])
        encrypted = base64.b64decode(encrypted_data["encrypted"])
        key = KeyManager.derive_key(password, salt)
        decrypted = bytes(a ^ b for a, b in zip(encrypted, key * (len(encrypted) // len(key))))
        length = int.from_bytes(decrypted[:4], 'big')
        data_bytes = decrypted[4:4 + length]
        return json.loads(data_bytes.decode())

    @staticmethod
    def load_keys(key_file: str) -> tuple:
        if not os.path.exists(key_file):
            logger.info("No key file found. Creating new key file.")
            api_key = input("Enter Binance API Key: ")
            api_secret = input("Enter Binance API Secret: ")
            password = getpass.getpass("Set password for key encryption: ")
            data = {"api_key": api_key, "api_secret": api_secret}
            encrypted_data = KeyManager.encrypt_data(data, password)
            with open(key_file, "w") as f:
                json.dump(encrypted_data, f)
            return api_key, api_secret
        else:
            for _ in range(3):
                password = getpass.getpass("Enter password to decrypt keys: ")
                try:
                    with open(key_file, "r") as f:
                        encrypted_data = json.load(f)
                    data = KeyManager.decrypt_data(encrypted_data, password)
                    return data["api_key"], data["api_secret"]
                except Exception as e:
                    logger.error(f"Decryption failed: {e}")
            raise Exception("Failed to decrypt keys after 3 attempts")