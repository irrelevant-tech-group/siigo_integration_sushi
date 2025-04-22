import requests
import json
import os
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

def test_credentials():
    # Obtener credenciales directamente
    username = os.getenv("SIIGO_USERNAME")
    access_key = os.getenv("SIIGO_ACCESS_KEY")
    partner_id = os.getenv("SIIGO_PARTNER_ID")
    
    print("Credenciales obtenidas:")
    print(f"Usuario: {username}")
    print(f"Access Key: {access_key[:5]}...{access_key[-5:]}")  # Mostrar solo parte de la clave
    print(f"Partner ID: {partner_id}")
    
    # Probar autenticación
    url = "https://api.siigo.com/auth"
    
    headers = {
        "Content-Type": "application/json",
        "Partner-Id": partner_id
    }
    
    # Método 1: Usando diccionario y json parameter
    data = {
        "username": username,
        "access_key": access_key
    }
    
    print("\nIntentando autenticación (método 1)...")
    response1 = requests.post(url, headers=headers, json=data)
    print(f"Código de estado: {response1.status_code}")
    print(f"Respuesta: {response1.text}")
    
    # Método 2: Usando string JSON con dumps
    json_data = json.dumps({
        "username": username,
        "access_key": access_key
    })
    
    print("\nIntentando autenticación (método 2)...")
    response2 = requests.post(url, headers=headers, data=json_data)
    print(f"Código de estado: {response2.status_code}")
    print(f"Respuesta: {response2.text}")
    
    # Método 3: Usando credenciales hardcodeadas (las que usaste en tu script previo)
    json_data_hard = json.dumps({
        "username": "siigoapi@pruebas.com",
        "access_key": "OWE1OGNkY2QtZGY4ZC00Nzg1LThlZGYtNmExMzUzMmE4Yzc1Omt2YS4yJTUyQEU="
    })
    
    print("\nIntentando autenticación (método 3 - hardcoded)...")
    response3 = requests.post(url, headers=headers, data=json_data_hard)
    print(f"Código de estado: {response3.status_code}")
    print(f"Respuesta: {response3.text}")

if __name__ == "__main__":
    test_credentials()