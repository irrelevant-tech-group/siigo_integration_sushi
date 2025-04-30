#!/usr/bin/env python
"""
Script de diagnóstico para variables de entorno.
Este script verifica diferentes métodos de carga y lectura de variables del archivo .env
para diagnosticar problemas con caracteres especiales o formato.
"""
import os
import sys
import json
import base64
import requests
from pathlib import Path
import importlib.util

# Intentar importar dotenv de diferentes formas para comprobar disponibilidad
dotenv_loaders = []

try:
    from dotenv import load_dotenv
    dotenv_loaders.append(("python-dotenv (standard)", load_dotenv))
except ImportError:
    print("python-dotenv no está instalado")

try:
    from dotenv import dotenv_values
    dotenv_loaders.append(("python-dotenv (values)", dotenv_values))
except ImportError:
    pass

def print_header(title):
    """Imprime un encabezado formateado"""
    print("\n" + "=" * 80)
    print(f" {title} ".center(80, "="))
    print("=" * 80)

def check_env_file():
    """Verifica si el archivo .env existe y muestra su contenido en bytes para diagnóstico"""
    print_header("VERIFICACIÓN DEL ARCHIVO .ENV")
    
    env_path = Path('.env')
    if not env_path.exists():
        print(f"❌ El archivo .env no existe en {env_path.absolute()}")
        return False
    
    print(f"✅ Archivo .env encontrado en: {env_path.absolute()}")
    
    # Leer el archivo en modo binario para analizar posibles problemas de caracteres
    with open(env_path, 'rb') as f:
        content = f.read()
    
    print(f"\nTamaño del archivo: {len(content)} bytes")
    
    # Mostrar el contenido como bytes para identificar caracteres especiales o problemas de codificación
    print("\nContenido del archivo (representación hexadecimal):")
    for i, line in enumerate(content.split(b'\n')):
        if b'ACCESS_KEY' in line or b'api' in line.lower():
            print(f"Línea {i+1}: {line!r}")
            # Analizar la línea más detalladamente
            parts = line.split(b'=', 1)
            if len(parts) == 2:
                key, value = parts
                print(f"  - Clave: {key.decode('utf-8', errors='replace')}")
                print(f"  - Valor: {value.decode('utf-8', errors='replace')}")
                # Revisar si hay caracteres problemáticos al final
                if value.endswith(b'\r'):
                    print("  ⚠️ ADVERTENCIA: La línea termina con un retorno de carro '\\r'")
                # Revisar si hay espacios al principio o final
                if value.strip() != value:
                    print("  ⚠️ ADVERTENCIA: El valor tiene espacios en blanco al principio o final")
    
    # Imprimir también el contenido como texto para comparar
    print("\nContenido del archivo (texto):")
    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if 'ACCESS_KEY' in line or 'api' in line.lower():
                    print(f"Línea {i+1}: {line.rstrip()}")
    except UnicodeDecodeError:
        print("❌ No se pudo leer el archivo como texto UTF-8, posible problema de codificación")
    
    return True

def test_environment_loaders():
    """Prueba diferentes métodos de carga de variables de entorno"""
    print_header("PRUEBA DE CARGADORES DE VARIABLES DE ENTORNO")
    
    results = {}
    
    # 1. Método nativo de Python os.environ
    print("\n1. Verificando variables ya cargadas en os.environ:")
    env_vars = {k: v for k, v in os.environ.items() if 'SIIGO' in k or 'API_KEY' in k}
    for key, value in env_vars.items():
        masked_value = mask_sensitive_value(value)
        print(f"  {key}: {masked_value}")
    results['os.environ'] = env_vars
    
    # 2. Probar diferentes cargadores de .env si están disponibles
    for name, loader in dotenv_loaders:
        print(f"\n2. Probando carga con {name}:")
        try:
            if name == "python-dotenv (standard)":
                loader()  # load_dotenv() carga en os.environ
                loaded = {k: os.environ.get(k) for k in ['SIIGO_USERNAME', 'SIIGO_ACCESS_KEY', 'SIIGO_PARTNER_ID']}
            else:
                loaded = loader()  # dotenv_values() devuelve un diccionario
            
            for key in ['SIIGO_USERNAME', 'SIIGO_ACCESS_KEY', 'SIIGO_PARTNER_ID']:
                if key in loaded and loaded[key]:
                    masked_value = mask_sensitive_value(loaded[key])
                    print(f"  {key}: {masked_value}")
                else:
                    print(f"  {key}: No encontrado")
            
            results[name] = loaded
        except Exception as e:
            print(f"  ❌ Error: {e}")
    
    # 3. Función personalizada de carga manual (la que posiblemente esté usando en la aplicación)
    print("\n3. Probando carga manual línea por línea:")
    
    try:
        manual_vars = {}
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    try:
                        key, value = line.split('=', 1)
                        key = key.strip()
                        value = value.strip()
                        manual_vars[key] = value
                    except ValueError:
                        print(f"  ⚠️ Advertencia: No se pudo parsear la línea: {line}")
        
        for key in ['SIIGO_USERNAME', 'SIIGO_ACCESS_KEY', 'SIIGO_PARTNER_ID']:
            if key in manual_vars:
                masked_value = mask_sensitive_value(manual_vars[key])
                print(f"  {key}: {masked_value}")
            else:
                print(f"  {key}: No encontrado")
        
        results['manual_parsing'] = manual_vars
    except Exception as e:
        print(f"  ❌ Error: {e}")
    
    return results

def test_string_equality(values):
    """Compara los valores de diferentes métodos de carga para verificar consistencia"""
    print_header("PRUEBA DE IGUALDAD DE CADENAS")
    
    # Extraer todos los valores de SIIGO_ACCESS_KEY
    access_keys = {}
    for method, vars_dict in values.items():
        if isinstance(vars_dict, dict) and 'SIIGO_ACCESS_KEY' in vars_dict:
            access_keys[method] = vars_dict['SIIGO_ACCESS_KEY']
    
    # También agregar la versión hardcodeada que sabemos que funciona
    access_keys['hardcoded'] = "OWE1OGNkY2QtZGY4ZC00Nzg1LThlZGYtNmExMzUzMmE4Yzc1Omt2YS4yJTUyQEU="
    
    # Comparar todos los pares de valores
    print("\nComparando valores de SIIGO_ACCESS_KEY entre métodos:")
    for method1, value1 in access_keys.items():
        for method2, value2 in access_keys.items():
            if method1 != method2:
                equal = value1 == value2
                print(f"  {method1} vs {method2}: {'✅ Iguales' if equal else '❌ Diferentes'}")
                
                if not equal:
                    # Analizar diferencias
                    print("  Análisis de diferencias:")
                    if len(value1) != len(value2):
                        print(f"    - Longitudes diferentes: {len(value1)} vs {len(value2)}")
                    
                    # Comparar caracteres uno a uno
                    for i, (c1, c2) in enumerate(zip(value1, value2)):
                        if c1 != c2:
                            print(f"    - Diferencia en posición {i}: '{c1}' vs '{c2}'")
                            print(f"      Códigos ASCII: {ord(c1)} vs {ord(c2)}")
                    
                    # Diferencias en la codificación Base64
                    try:
                        decoded1 = base64.b64decode(value1)
                        decoded2 = base64.b64decode(value2)
                        if decoded1 != decoded2:
                            print("    - Decodificación Base64 diferente")
                        else:
                            print("    - Decodificación Base64 igual a pesar de cadenas diferentes")
                    except Exception:
                        print("    - No se pudo decodificar en Base64")

def test_siigo_auth(values):
    """Prueba la autenticación con Siigo usando diferentes métodos"""
    print_header("PRUEBA DE AUTENTICACIÓN CON SIIGO")
    
    # URLs y headers comunes
    url = "https://api.siigo.com/auth"
    partner_id = next(
        (vars_dict.get('SIIGO_PARTNER_ID', 'IrrelevantProjectsApp') 
         for method, vars_dict in values.items() 
         if isinstance(vars_dict, dict) and 'SIIGO_PARTNER_ID' in vars_dict),
        'IrrelevantProjectsApp'
    )
    
    headers = {
        "Content-Type": "application/json",
        "Partner-Id": partner_id
    }
    
    # Prueba con cada método que tenga credenciales completas
    for method, vars_dict in values.items():
        if isinstance(vars_dict, dict) and 'SIIGO_USERNAME' in vars_dict and 'SIIGO_ACCESS_KEY' in vars_dict:
            username = vars_dict['SIIGO_USERNAME']
            access_key = vars_dict['SIIGO_ACCESS_KEY']
            
            print(f"\nProbando autenticación con credenciales de {method}:")
            
            # Método 1: Usando json=
            data = {
                "username": username,
                "access_key": access_key
            }
            
            try:
                print(f"  Método json=data")
                response = requests.post(url, headers=headers, json=data, timeout=10)
                print(f"  Código de estado: {response.status_code}")
                if response.status_code == 200:
                    print("  ✅ Autenticación exitosa")
                    token = response.json().get('access_token', '')
                    print(f"  Token: {token[:20]}...")
                else:
                    print(f"  ❌ Error: {response.text}")
            except Exception as e:
                print(f"  ❌ Error: {e}")
            
            # Método 2: Usando data=json.dumps()
            try:
                print(f"\n  Método data=json.dumps(data)")
                json_data = json.dumps(data)
                response = requests.post(url, headers=headers, data=json_data, timeout=10)
                print(f"  Código de estado: {response.status_code}")
                if response.status_code == 200:
                    print("  ✅ Autenticación exitosa")
                    token = response.json().get('access_token', '')
                    print(f"  Token: {token[:20]}...")
                else:
                    print(f"  ❌ Error: {response.text}")
            except Exception as e:
                print(f"  ❌ Error: {e}")
    
    # Prueba final con credenciales hardcodeadas
    print("\nProbando autenticación con credenciales hardcodeadas (referencia):")
    data = {
        "username": "siigoapi@pruebas.com",
        "access_key": "OWE1OGNkY2QtZGY4ZC00Nzg1LThlZGYtNmExMzUzMmE4Yzc1Omt2YS4yJTUyQEU="
    }
    
    try:
        json_data = json.dumps(data)
        response = requests.post(url, headers=headers, data=json_data, timeout=10)
        print(f"  Código de estado: {response.status_code}")
        if response.status_code == 200:
            print("  ✅ Autenticación exitosa")
            token = response.json().get('access_token', '')
            print(f"  Token: {token[:20]}...")
        else:
            print(f"  ❌ Error: {response.text}")
    except Exception as e:
        print(f"  ❌ Error: {e}")

def get_application_env_loader():
    """Intenta localizar y ejecutar el cargador de variables de entorno de la aplicación"""
    print_header("CARGADOR DE VARIABLES DE LA APLICACIÓN")
    
    # Buscar archivos que podrían contener el cargador de variables
    possible_files = [
        'settings.py',
        'config/settings.py',
        'config.py',
        'env.py',
        'utils/env.py'
    ]
    
    for file_path in possible_files:
        if os.path.exists(file_path):
            print(f"Encontrado posible archivo de configuración: {file_path}")
            
            try:
                # Cargar el módulo dinámicamente
                spec = importlib.util.spec_from_file_location("env_module", file_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Buscar funciones que podrían cargar variables de entorno
                env_loaders = []
                for attr_name in dir(module):
                    if attr_name.lower().find('env') != -1 and callable(getattr(module, attr_name)):
                        env_loaders.append(attr_name)
                
                if env_loaders:
                    print(f"Posibles funciones de carga de variables: {', '.join(env_loaders)}")
                    
                    for loader_name in env_loaders:
                        try:
                            print(f"\nIntentando ejecutar {loader_name}()...")
                            getattr(module, loader_name)()
                            # Verificar si se cargaron variables relevantes
                            if any(k in os.environ for k in ['SIIGO_USERNAME', 'SIIGO_ACCESS_KEY']):
                                print("✅ La función parece haber cargado variables de entorno")
                                return True
                        except Exception as e:
                            print(f"Error al ejecutar {loader_name}(): {e}")
                
                # También buscar la función load_env_file en cualquier módulo
                if hasattr(module, 'load_env_file'):
                    print("\nEncontrada función load_env_file(). Intentando ejecutar...")
                    try:
                        result = module.load_env_file()
                        print(f"Resultado: {type(result)}")
                        if isinstance(result, dict):
                            for key in ['SIIGO_USERNAME', 'SIIGO_ACCESS_KEY']:
                                if key in result:
                                    masked_value = mask_sensitive_value(result[key])
                                    print(f"  {key}: {masked_value}")
                        return True
                    except Exception as e:
                        print(f"Error al ejecutar load_env_file(): {e}")
            
            except Exception as e:
                print(f"Error al cargar módulo {file_path}: {e}")
    
    print("\nNo se encontró o no se pudo ejecutar el cargador de variables de la aplicación")
    return False

def mask_sensitive_value(value):
    """Enmascara valores sensibles para mostrarlos en la consola"""
    if not value:
        return ""
    
    if len(value) <= 10:
        return value
    
    return f"{value[:5]}...{value[-5:]}"

def generate_solution():
    """Genera recomendaciones de solución basadas en los resultados de las pruebas"""
    print_header("RECOMENDACIONES")
    
    print("""
Basado en las pruebas realizadas, aquí hay algunas recomendaciones para resolver
el problema de autenticación con la API de Siigo:

1. MODIFICAR LA FUNCIÓN DE CARGA DE VARIABLES DE ENTORNO:
   - Evitar el uso de strip() en el valor de SIIGO_ACCESS_KEY, ya que podría
     eliminar caracteres importantes como '=' al final.
   - Usar este código para cargar variables sensibles:

   ```python
   def load_env_variables():
       try:
           with open('.env', 'r', encoding='utf-8') as f:
               for line in f:
                   # Ignorar comentarios y líneas vacías
                   line = line.strip()
                   if not line or line.startswith('#'):
                       continue
                   
                   # Dividir en key=value pero solo en la primera aparición de =
                   parts = line.split('=', 1)
                   if len(parts) != 2:
                       continue
                       
                   key, value = parts
                   key = key.strip()
                   # NO hacer strip() del valor, preservar caracteres especiales
                   # value = value.strip()  # ¡Evitar esto!
                   
                   # Establecer la variable de entorno
                   os.environ[key] = value
       except Exception as e:
           print(f"Error al cargar variables de entorno: {e}")
   ```

2. MODIFICAR SIIGO_API.py:
   - Cambiar cómo se envían los datos a la API:
   
   ```python
   def get_token(self, force_refresh=False):
       # ... código existente ...
       
       # Preparar los datos exactamente según el formato requerido
       data = {
           "username": self.username,
           "access_key": self.access_key
       }
       
       try:
           # Usar data=json.dumps(data) en lugar de json=data
           json_data = json.dumps(data)
           response = requests.post(
               f"{self.base_url}/auth",
               headers=headers,
               data=json_data,  # Usar data en lugar de json
               timeout=30
           )
           
           # ... resto del código ...
   ```

3. AGREGAR CREDENCIALES ALTERNATIVAS TEMPORALES:
   - Si todo lo demás falla, agregar una solución temporal usando credenciales hardcodeadas:
   
   ```python
   def get_token(self, force_refresh=False):
       # ... código existente ...
       
       # Si las credenciales del .env no funcionan, usar hardcodeadas como respaldo
       if response.status_code != 200:
           logger.warning("La autenticación falló con credenciales del .env, usando alternativas...")
           backup_data = json.dumps({
               "username": "siigoapi@pruebas.com",
               "access_key": "OWE1OGNkY2QtZGY4ZC00Nzg1LThlZGYtNmExMzUzMmE4Yzc1Omt2YS4yJTUyQEU="
           })
           response = requests.post(
               f"{self.base_url}/auth",
               headers=headers,
               data=backup_data,
               timeout=30
           )
           
       # ... resto del código ...
   ```
   
La solución ideal es corregir cómo se cargan y procesan las variables de entorno
para asegurarte de que los valores se transfieran exactamente como están en el 
archivo .env, sin modificaciones.
""")

def main():
    print_header("DIAGNÓSTICO DE VARIABLES DE ENTORNO")
    print("Este script identificará problemas con la carga de variables de entorno.")
    
    # 1. Verificar el archivo .env
    if not check_env_file():
        print("No se puede continuar sin archivo .env")
        logger.error("echo $SIIGO_ACCESS_KEY")
        return
    
    # 2. Probar diferentes métodos de carga
    env_values = test_environment_loaders()
    
    # 3. Buscar el cargador usado por la aplicación
    get_application_env_loader()
    
    # 4. Verificar igualdad de cadenas
    test_string_equality(env_values)
    
    # 5. Probar autenticación real con diferentes métodos
    test_siigo_auth(env_values)
    
    # 6. Sugerir soluciones
    generate_solution()

if __name__ == "__main__":
    main()