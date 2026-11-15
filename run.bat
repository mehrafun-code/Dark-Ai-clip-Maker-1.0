@echo off
echo Libraries install ho rahi hain (pehli baar time lagega)...
pip install -r requirements.txt
streamlit run app.py --theme.base=dark --theme.primaryColor=#e11d48 --theme.backgroundColor=#0b0b10 --theme.secondaryBackgroundColor=#14141c --theme.textColor=#eaeaf0
pause
