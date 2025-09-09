cd ~/Documents
git clone https://github.com/KoljaB/RealtimeSTT.git
cd RealtimeSTT

# tạo môi trường ảo

python3 -m venv venv

# kích hoạt môi trường ảo

source venv/bin/activate

pip install --upgrade pip
pip install -r requirements.txt

python .\example_webserver\server.py
python .\example_browserclient\server.py

venv\Scripts\activate && python .\example_webserver\client.py
