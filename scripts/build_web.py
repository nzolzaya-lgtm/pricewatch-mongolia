"""Build the browser-hosted Streamlit app and a ready-to-run source ZIP."""
from pathlib import Path
import json
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
DIST=ROOT/'dist'
DIST.mkdir(exist_ok=True)
runtime=['app.py','prices.py','downloads.py','assets/style.css','.streamlit/config.toml',
         'data/prices.csv','data/catalogue.json','data/snapshot.json']
source=runtime+['requirements.txt','README.md','scripts/fetch_snapshot.py','scripts/build_web.py','tests/test_prices.py',
                'data/nso_metadata_en.json','data/nso_metadata_mn.json','data/nso_query.json','data/nso_response.json.gz']
for name in runtime:
    target=DIST/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
archive=DIST/'PriceWatch_Mongolia_Streamlit.zip'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as z:
    for name in source:z.write(ROOT/name,'PriceWatch_Mongolia/'+name)
with zipfile.ZipFile(archive) as z:assert z.testzip() is None
files={name:{'url':'./'+name} for name in runtime}
files['dist/'+archive.name]={'url':'./'+archive.name}
settings={'requirements':[], 'entrypoint':'app.py','files':files,
          'streamlitConfig':{'theme.primaryColor':'#147D62','theme.backgroundColor':'#F4F7FA',
            'theme.secondaryBackgroundColor':'#FFFFFF','theme.textColor':'#172C3C',
            'theme.font':'sans serif','client.toolbarMode':'minimal'}}
html='''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="Build a grocery basket and compare real official monthly price data across Mongolia."><meta name="theme-color" content="#147D62"><title>PriceWatch Mongolia</title><link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'%3E%3Crect width='48' height='48' rx='13' fill='%23147d62'/%3E%3Ctext x='11' y='34' fill='white' font-family='sans-serif' font-size='32'%3E%E2%82%AE%3C/text%3E%3C/svg%3E"><link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@stlite/browser@0.85.1/build/stlite.css"><style>html,body{margin:0;background:#f4f7fa;font-family:system-ui;color:#172c3c}#boot{position:fixed;inset:0;background:#f4f7fa;display:grid;place-items:center;z-index:10000}#boot .card{text-align:center;max-width:430px;padding:28px}.logo{display:grid;place-items:center;width:60px;height:60px;background:#147d62;color:white;font-weight:700;font-size:34px;border-radius:17px;margin:auto}h1{font-size:29px;letter-spacing:-1px;margin:23px 0 10px}p{font-size:16px;line-height:1.7;color:#617484}a{color:#147d62;font-size:14px}.load{margin:23px auto;width:155px;height:4px;border-radius:4px;overflow:hidden;background:#dbe7e2}.load:before{content:'';display:block;width:60px;height:4px;background:#147d62;animation:loading 1.3s infinite ease-in-out}@keyframes loading{from{transform:translateX(-60px)}to{transform:translateX(165px)}}#root{min-height:100vh}</style></head><body><div id="boot"><div class="card"><div class="logo">₮</div><h1>Let’s make sense of prices.</h1><p id="loading-copy">Opening your Streamlit app and the official price snapshot.<br>The first visit loads Python in your browser.</p><div class="load"></div><a href="./PriceWatch_Mongolia_Streamlit.zip" download>Download the Python project</a></div></div><main id="root"></main><noscript>Enable JavaScript to open the planner, or download the Python project to run it with Streamlit.</noscript><script type="module">
const settings=SETTINGS;
for(const file of Object.values(settings.files))file.url=new URL(file.url,location.href).href;
settings.files['web_context.json']=JSON.stringify({downloads:{'PriceWatch_NSO_price_grid.csv':new URL('./data/prices.csv',location.href).href,'PriceWatch_Mongolia_Streamlit.zip':new URL('./PriceWatch_Mongolia_Streamlit.zip',location.href).href}});
const observer=new MutationObserver(()=>{if(document.querySelector('[data-testid="stAppViewContainer"]')){document.getElementById('boot')?.remove();observer.disconnect();}});observer.observe(document.getElementById('root'),{subtree:true,childList:true});
setTimeout(()=>{const c=document.getElementById('loading-copy');if(c)c.textContent='The first launch can take a minute while Python and the data load. You can also download the Streamlit project below.';},30000);
try{const {mount}=await import('https://cdn.jsdelivr.net/npm/@stlite/browser@0.85.1/build/stlite.js');mount(settings,document.getElementById('root'));}catch(e){document.getElementById('loading-copy').textContent='The browser runtime could not load. Check your connection or download the Python project below.';document.querySelector('.load').style.display='none';console.error('PriceWatch startup failed',e);}
</script></body></html>'''.replace('SETTINGS',json.dumps(settings,ensure_ascii=False).replace('</','<\\/'))
(DIST/'index.html').write_text(html,encoding='utf-8')
print(json.dumps({'dist':str(DIST),'source_zip':str(archive),'zip_bytes':archive.stat().st_size,'runtime_files':len(runtime)}))
