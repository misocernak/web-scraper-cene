from flask import Flask, request, jsonify, send_file
import pandas as pd
import requests
from bs4 import BeautifulSoup
import os
import uuid
import time
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

def scrape_price(site, url_template, search_term, selector):
    try:
        url = url_template.format(search_term.replace(' ', '+'))
        logger.info(f"Scrapujem {site} za uređaj: {search_term}, URL: {url}")
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=5)
        soup = BeautifulSoup(response.text, 'html.parser')
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
        results = []
        
        scrape_progress['total'] = len(devices)
        scrape_progress['progress'] = 0
        scrape_progress['status'] = 'running'

        for device in devices:
            device_result = {'Uređaj': device}
            for site, config in SITES.items():
                price = scrape_price(site, config['url_template'], device, config['selector'])
                device_result[site] = price if price else 'N/A'
                time.sleep(1)  # Pauza između zahteva da izbegnemo blokiranje
            results.append(device_result)
            scrape_progress['progress'] += 1
            logger.info(f"Završeno scrapovanje za uređaj: {device}, napredak: {scrape_progress['progress']}/{scrape_progress['total']}")

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
            
            # Sinhrono pokretanje scraping-a
            logger.info("Pokrećem scraping")
            output_file = scrape_prices(devices)
            return jsonify({'message': 'Scraping završen', 'output_file': output_file})
        except Exception as e:
            logger.error(f"Greška prilikom obrade fajla: {str(e)}")
            return jsonify({'error': f'Greška prilikom scrapinga: {str(e)}'}), 500
    
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
