import os
import sys
import time
import zipfile
import threading
import subprocess
import configparser
from pathlib import Path
from queue import Queue, Empty
from tkinter import filedialog, messagebox, scrolledtext
import tkinter as tk
from PIL import Image, ImageTk
import logging
from datetime import datetime
import psutil

logging.basicConfig(
    filename='impresion_etiquetas.log',
    level=logging.ERROR,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%d-%m-%Y %H:%M:%S'
)

config_file = "config.ini"

def cargar_ruta_adobe():
    config = configparser.ConfigParser()
    if os.path.exists(config_file):
        config.read(config_file)
        if 'Config' in config and 'adobe_path' in config['Config']:
            return config['Config']['adobe_path']
    return None

def guardar_ruta_adobe(ruta):
    config = configparser.ConfigParser()
    config['Config'] = {'adobe_path': ruta}
    with open(config_file, 'w') as configfile:
        config.write(configfile)

def cerrar_procesos_acrobat():
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if proc.info['name'] in ["Acrobat.exe", "AcroRd32.exe"] and 'AcroRd32.exe' in proc.info['cmdline']:
                proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess) as e:
            logging.error(f"Error al cerrar el proceso de Acrobat {proc.info['pid']}: {e}")

def imprimir_documento_con_acrobat(adobe_path, pdf_file, impresora):
    try:
        pdf_file = os.path.abspath(pdf_file)
        working_dir = os.path.dirname(pdf_file)
        comando_impresion = f'"{adobe_path}" /s /h /t "{pdf_file}" "{impresora}"'
        logging.info(f"Comando de impresión ejecutado: {comando_impresion}")
        resultado = subprocess.run(comando_impresion, shell=True, check=True, cwd=working_dir)
        time.sleep(1)
        cerrar_procesos_acrobat()
        return resultado.returncode == 0
    except Exception as e:
        logging.error(f"Error en la impresión con Adobe Acrobat: {e}")
        return False

class Aplicacion:
    def __init__(self, root):
        self.root = root
        self.root.title("Atmósfera Sport - Monitoreo e Impresión")
        self.root.geometry("500x500")
        self.root.resizable(False, False)
        self.logo_tk = None
        self.lock = threading.Lock()
        self.cola_impresion = Queue()
        self.crear_primera_ventana()

    def crear_primera_ventana(self):
        try:
            ruta_logo = 'logo_atmosfera_sport.jpg'
            self.logo = Image.open(ruta_logo)
            self.logo = self.logo.resize((400, 100))
            self.logo_tk = ImageTk.PhotoImage(self.logo)
            self.logo_label = tk.Label(self.root, image=self.logo_tk)
            self.logo_label.pack(pady=10)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo cargar el logo. Detalles: {e}")

        self.label_carpeta = tk.Label(self.root, text="Seleccionar la carpeta a monitorear:", font=("Arial", 12))
        self.label_carpeta.pack(pady=5)
        self.boton_carpeta = tk.Button(self.root, text="Seleccionar carpeta", command=self.seleccionar_carpeta)
        self.boton_carpeta.pack(pady=5)

        self.label_impresora = tk.Label(self.root, text="Escriba el nombre de la impresora:", font=("Arial", 12))
        self.label_impresora.pack(pady=5)
        self.entry_impresora = tk.Entry(self.root, width=40)
        self.entry_impresora.pack(pady=5)

        self.boton_confirmar = tk.Button(self.root, text="Confirmar", command=self.abrir_segunda_ventana)
        self.boton_confirmar.pack(pady=10)

    def seleccionar_carpeta(self):
        carpeta = filedialog.askdirectory()
        if carpeta:
            self.carpeta_seleccionada = carpeta
            messagebox.showinfo("Carpeta seleccionada", f"Has seleccionado: {carpeta}")
        else:
            self.carpeta_seleccionada = None

    def abrir_segunda_ventana(self):
        if not hasattr(self, 'carpeta_seleccionada') or not self.carpeta_seleccionada:
            messagebox.showwarning("Error", "Debe seleccionar una carpeta.")
            return
        impresora = self.entry_impresora.get().strip()
        if not impresora:
            messagebox.showwarning("Error", "Debe ingresar el nombre de la impresora.")
            return

        adobe_path = cargar_ruta_adobe()
        if not adobe_path:
            messagebox.showwarning("Adobe Acrobat Reader no encontrado", "Seleccione la ubicación de AcroRd32.exe.")
            adobe_path = filedialog.askopenfilename(title="Seleccionar Adobe Acrobat Reader", filetypes=[("Ejecutable", "*.exe")])
            if adobe_path and os.path.exists(adobe_path):
                guardar_ruta_adobe(adobe_path)
            else:
                messagebox.showerror("Error", "No se encontró Adobe Acrobat Reader. La aplicación no puede continuar.")
                return

        self.root.withdraw()
        self.ventana_logs = tk.Toplevel()
        self.ventana_logs.title("Atmósfera Sport - Estado de la impresión")
        self.ventana_logs.geometry("500x500")
        self.ventana_logs.resizable(False, False)

        if self.logo_tk:
            self.logo_label_logs = tk.Label(self.ventana_logs, image=self.logo_tk)
            self.logo_label_logs.pack(pady=10)

        self.log_text = scrolledtext.ScrolledText(self.ventana_logs, width=60, height=15)
        self.log_text.pack(pady=10)
        self.ventana_logs.protocol("WM_DELETE_WINDOW", self.cerrar_aplicacion)

        self.mostrar_logs("Aplicación iniciada...\n")
        self.mostrar_logs(f"Usando Adobe Acrobat Reader en: {adobe_path}")

        threading.Thread(target=self.procesar_cola_impresion, args=(impresora, adobe_path), daemon=True).start()
        threading.Thread(target=self.iniciar_monitoreo, args=(self.carpeta_seleccionada,), daemon=True).start()

    def mostrar_logs(self, texto):
        self.root.after(0, lambda: self.log_text.insert(tk.END, texto + "\n"))
        self.root.after(0, lambda: self.log_text.see(tk.END))

    def iniciar_monitoreo(self, carpeta):
        self.mostrar_logs(f"Monitoreando la carpeta: {carpeta}")
        carpeta_descargas = Path(carpeta)
        archivos_anteriores = set(os.listdir(carpeta_descargas))

        while True:
            try:
                archivos_actuales = set(os.listdir(carpeta_descargas))
                nuevos_archivos = archivos_actuales - archivos_anteriores
                for archivo in nuevos_archivos:
                    ruta_completa = carpeta_descargas / archivo
                    if not archivo.startswith("Etiquetas") or not archivo.endswith(".zip"):
                        continue
                    try:
                        with open(ruta_completa, 'rb'):
                            pass
                        self.mostrar_logs(f"Nuevo archivo ZIP detectado: {ruta_completa}")
                        threading.Thread(target=self.manejar_zip, args=(ruta_completa,)).start()
                    except Exception as e:
                        self.mostrar_logs(f"Archivo incompleto o bloqueado: {archivo}")
                archivos_anteriores = archivos_actuales
                time.sleep(5)
            except Exception as e:
                self.mostrar_logs(f"Error en el monitoreo: {e}")
                logging.error(f"Error en el monitoreo: {e}")

    def manejar_zip(self, ruta_zip):
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            carpeta_temporal = Path(f'temp_etiquetas/{timestamp}')
            carpeta_temporal.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(ruta_zip, 'r') as zip_ref:
                zip_ref.extractall(carpeta_temporal)

            list_files = os.listdir(carpeta_temporal)
            list_pdfs = [carpeta_temporal / file for file in list_files if file.endswith('.pdf')]

            with self.lock:
                for pdf_file in list_pdfs:
                    self.cola_impresion.put(pdf_file)
                    self.mostrar_logs(f"Añadido a la cola de impresión: {pdf_file}")
        except zipfile.BadZipFile:
            self.mostrar_logs(f"El archivo ZIP {ruta_zip} está corrupto.")
        except Exception as e:
            self.mostrar_logs(f"Error al manejar el archivo ZIP {ruta_zip}: {e}")
            logging.error(f"Error al manejar el archivo ZIP {ruta_zip}: {e}")

    def procesar_cola_impresion(self, impresora, adobe_path):
        while True:
            try:
                # Intenta obtener el siguiente archivo en la cola con un tiempo de espera
                pdf_file = self.cola_impresion.get(timeout=10)
                self.mostrar_logs(f"Intentando imprimir: {pdf_file}")

                # Intenta imprimir el archivo
                exito = imprimir_documento_con_acrobat(adobe_path, pdf_file, impresora)
                if exito:
                    self.mostrar_logs(f"Impresión exitosa: {pdf_file}")
                else:
                    self.mostrar_logs(f"Falló la impresión de {pdf_file}.")
                
                # Marca el archivo como procesado
                self.cola_impresion.task_done()

            except Empty:
                # Si la cola está vacía, sigue esperando
                continue

            except Exception as e:
                # Maneja cualquier error inesperado para evitar que el hilo se bloquee
                logging.error(f"Error procesando el archivo {pdf_file}: {e}")
                self.mostrar_logs(f"Error inesperado al procesar: {e}")
                self.cola_impresion.task_done()  # Asegura que la cola no se quede bloqueada

    def cerrar_aplicacion(self):
        self.ventana_logs.destroy()
        self.root.quit()

if __name__ == "__main__":
    root = tk.Tk()
    app = Aplicacion(root)
    root.mainloop()
