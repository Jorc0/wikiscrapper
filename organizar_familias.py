import re
import json
from pathlib import Path

def preparar_entorno(ruta_base, archivo_categorias):
    # Read the categories file
    try:
        with open(archivo_categorias, "r", encoding="utf-8") as f:
            datos = f.read()
    except Exception as e:
        print(f"[!] Error al leer el archivo {archivo_categorias}: {e}")
        return

    # Patrones para cazar el nombre de la familia en sus dos variantes (insensible a mayúsculas)
    patron_of = r"botanical illustrations of ([a-z]+)"
    patron_prefijo = r"([a-z]+) \(?botanical illustrations"
    
    familias = set()
    
    # Procesar línea a línea
    for linea in datos.split('\n'):
        linea = linea.strip()
        # Ignorar líneas vacías, letras del índice o encabezados
        if not linea or linea in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ' or 'Subcategories' in linea:
            continue
            
        # Buscar coincidencias de forma insensible a mayúsculas
        match1 = re.search(patron_of, linea, re.IGNORECASE)
        match2 = re.search(patron_prefijo, linea, re.IGNORECASE)
        
        familia_encontrada = None
        if match1:
            # Capturamos y capitalizamos para estandarizar (ej: Acanthaceae)
            familia_encontrada = match1.group(1).capitalize()
        elif match2:
            familia_encontrada = match2.group(1).capitalize()
            
        # Excluir algas (phyceae) y divisiones generales (phyta)
        if familia_encontrada and not familia_encontrada.lower().endswith(('phyceae', 'phyta')):
            familias.add(familia_encontrada)

    # Crear el directorio base
    directorio_raiz = Path(ruta_base)
    directorio_raiz.mkdir(parents=True, exist_ok=True)
    
    diccionario_indice = {}
    
    # Generar carpetas e índice
    for familia in sorted(familias):
        carpeta_familia = directorio_raiz / familia
        carpeta_familia.mkdir(exist_ok=True)
        # Guardamos la ruta relativa al espacio de trabajo o absoluta
        diccionario_indice[familia] = str(carpeta_familia.resolve())
        
    # Guardar el índice como JSON
    archivo_indice = directorio_raiz / "indice_familias.json"
    with open(archivo_indice, 'w', encoding='utf-8') as f:
        json.dump(diccionario_indice, f, indent=4, ensure_ascii=False)
        
    print(f"[+] ¡Éxito! Se han creado {len(familias)} carpetas de familias botánicas.")
    print(f"[+] Índice de familias guardado en: {archivo_indice}")
    return diccionario_indice

if __name__ == "__main__":
    # Guarda la colección en una carpeta dentro del espacio de trabajo
    preparar_entorno("./Coleccion_Botanica", "./categorias")
