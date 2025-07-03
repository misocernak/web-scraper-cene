from flask import Flask, request, jsonify, send_file
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from bs4 import BeautifulSoup
import pandas as pd
import os
import uuid
import time
from threading import Thread
import logging

app = Flask(__name__)

# Konfiguracija logging-a
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Konfiguracija sajtova i njihovih selektora cena
SITES = {
    'fonly.rs': {'selector': '.woocommerce-Price-amount.amount', 'url_template': 'https://fonly.rs/?s={}&post_type=product'},
    'shoppster.rs': {'selector': '.price-value', 'url_template': 'https://www.shoppster.rs/search?term={}'},
    'gigatron.rs': {'selector': '[itemprop="price"]', 'url_template': 'https://www.gigatron.rs/pretraga?trazi={}'},
    'tehnomanija.rs': {'selector': '.price', 'url_template': 'https://www.tehnomanija.rs/sr-rs/search?q={}'},
    'ananas.rs': {'selector': '.sc-1arj7wv-2.fXyDjU', 'url_template': 'https://www.ananas.rs/search?q={}'}
}

# Globalne promenljive za praćenje progress-a
scrape_progress = {'status': 'idle', 'progress': 0, 'total': 0, 'output_file': None}

def setup_driver():
    logger.info("Pokrećem ChromeDriver...")
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36')
    chrome_options.binary_location = os.environ.get('CHROME_BINARY', '/usr/bin/google-chrome')
    try:
        from chromedriver_binary import chromedriver_filename
        service = Service(chromedriver_filename)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logger.info("ChromeDriver uspešno pokrenut.")
        return driver
    except Exception as e:
        logger.error(f"Greška prilikom pokretanja ChromeDriver-a: {str(e)}")
        raise

def scrape_price(driver, site, url_template, search_term, selector):
    try:
        url = url_template.format(search_term.replace(' ', '+'))
        logger.info(f"Scrapujem {site} za uređaj: {search_term}, URL: {url}")
        driver.get(url)
        time.sleep(5)  # Povećano čekanje za stabilnost
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        price_element = soup.select_one(selector)
        if price_element:
            price = price_element.text.strip().replace('RSD', '').replace('din', '').replace(',', '').replace('.', '').strip()
            logger.info(f"Pronađena cena na {site}: {price}")
            return float(price) if price.replace('.', '').isdigit() else None
        else:
            logger.warning(f"Nije pronađena cena na {site} za selektor: {selector}")
            return None
    except Exception as e:
        logger.error(f"Greška prilikom scrapovanja {site}: {str(e)}")
        return None

def scrape_prices(devices):
    global scrape_progress
    logger.info(f"Pokrećem scraping za {len(devices)} uređaja: {devices}")
    try:
        driver = setup_driver()
        results = []
        
        scrape_progress['total'] = len(devices)
        scrape_progress['progress'] = 0
        scrape_progress['status'] = 'running'

        for device in devices:
            device_result = {'Uređaj': device}
            for site, config in SITES.items():
                price = scrape_price(driver, site, config['url_template'], device, config['selector'])
                device_result[site] = price if price else 'N/A'
            
            results.append(device_result)
            scrape_progress['progress'] += 1
            logger.info(f"Završeno scrapovanje za uređaj: {device}, napredak: {scrape_progress['progress']}/{scrape_progress['total']}")

        driver.quit()
        
        # Kreiranje izlaznog fajla
        output_file = f'output_{uuid.uuid4().hex}.xlsx'
        logger.info(f"Kreiram izlazni fajl: {output_file}")
        df = pd.DataFrame(results)
        df.to_excel(output_file, index=False)
        
        scrape_progress['status'] = 'completed'
        scrape_progress['output_file'] = output_file
        logger.info("Scraping završen, fajl spreman.")
        return output_file
    except Exception as e:
        logger.error(f"Greška u scrape_prices: {str(e)}")
        scrape_progress['status'] = 'error'
        scrape_progress['output_file'] = None
        raise

@app.route('/')
def index():
    logger.info("Pristup index stranici")
    return app.send_static_file('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    global scrape_progress
    logger.info("Pristup /upload ruti")
    if 'file' not in request.files:
        logger.error("Nema fajla u zahtevu")
        return jsonify({'error': 'Nema fajla'}), 400
    
    file = request.files['file']
    if file.filename == '':
        logger.error("Nije izabran fajl")
        return jsonify({'error': 'Nije izabran fajl'}), 400
    
    if file and file.filename.endswith('.xlsx'):
        try:
            logger.info(f"Učitavam Excel fajl: {file.filename}")
            df = pd.read_excel(file)
            devices = df.iloc[:, 0].tolist()  # Pretpostavka da je prva kolona naziv uređaja
            logger.info(f"Pronađeno {len(devices)} uređaja: {devices}")
            
            # Resetovanje progress-a
            scrape_progress = {'status': 'running', 'progress': 0, 'total': len(devices), 'output_file': None}
            
            # Pokretanje scraping-a u posebnom thread-u
            logger.info("Pokrećem scraping thread")
            Thread(target=scrape_prices, args=(devices,)).start()
            return jsonify({'message': 'Scraping započet'})
        except Exception as e:
            logger.error(f"Greška prilikom obrade fajla: {str(e)}")
            return jsonify({'error': f'Greška prilikom obrade fajla: {str(e)}'}), 400
    
    logger.error("Fajl nije .xlsx")
    return jsonify({'error': 'Fajl mora biti .xlsx'}), 400

@app.route('/progress')
def get_progress():
    logger.info(f"Vraćam status napretka: {scrape_progress}")
    return jsonify(scrape_progress)

@app.route('/download')
def download_file():
    logger.info("Pristup /download ruti")
    if scrape_progress['status'] == 'completed' and scrape_progress['output_file']:
        logger.info(f"Šaljem fajl: {scrape_progress['output_file']}")
        return send_file(scrape_progress['output_file'], as_attachment=True)
    logger.error("Fajl nije spreman za preuzimanje")
    return jsonify({'error': 'Fajl nije spreman'}), 400

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
