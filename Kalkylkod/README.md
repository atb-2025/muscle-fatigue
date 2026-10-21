# EMG Studio v3.1 – automatisk referens och valfritt sparande

## Uppdatera din befintliga installation

1. Stoppa servern med Ctrl+C i VS Code-terminalen.
2. Packa upp den nya ZIP-filen.
3. Kopiera över `server.py`, `emg_core.py`, `amplitude_index.py`, `index.html`,
   `simulate_esp32.py` och denna README till din befintliga EMG_Web-mapp.
   Ersätt de gamla filerna. Behåll `data/`, `.venv` och dina egna firmwareinställningar.
4. Starta igen:

```bash
source .venv/bin/activate
python3 server.py
```

5. Ladda om http://127.0.0.1:8000 i webbläsaren. Längst ner ska det stå **EMG Studio v3.1**.

Inga nya Python-paket behövs. Du behöver inte ladda upp Arduino-koden igen
för denna uppdatering, om kortets Wi-Fi och datasändning redan fungerar.

## Mina analyser 

- Klicka **Öppna** för att visa analysen. Hela den öppnade raden markeras grönt.
- Din valda trötthetsetikett visas i en liten färgad ruta bredvid analysnamnet.
  Ändra den under **Namn & egna anteckningar** och klicka **Spara anteckningar**.
  Ingen ruta visas om du har valt **Ingen etikett**.
- Soptunnan bredvid **Öppna** raderar analysen efter bekräftelse. Den försvinner
  direkt ur listan. Om den var öppen stängs dess resultatvy också.
  Sparade signalfiler behålls i `data/`.

Om du redan har v3 räcker det att ersätta `server.py` och `index.html`, starta
om servern och ladda om webbsidan. Behåll din befintliga `data/`-mapp.

## Första installationen på Mac

Öppna mappen EMG_Web i VS Code → Terminal → New Terminal. Med internetanslutning:

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 server.py
```

Webbläsaren försöker öppnas automatiskt. Annars öppnar du
**http://127.0.0.1:8000**. Behåll terminalen öppen under mätningen. Öppna inte
index.html genom dubbelklick: den behöver Python-servern. Python 3 och NumPy
räcker; Node används endast för ett frivilligt utvecklartest.

## Automatisk trötthetsindikator

Du ska inte längre trycka för att ge en referenspunkt.

1. Välj en inspelning som är minst cirka 10 sekunder och klicka Starta inspelning.
2. **Slappna av de första cirka 3 sekunderna.** Programmet mäter vilonivån.
3. När statusen säger **Börja övningen**, gör din övning med utvilad muskel.
4. Programmet samlar 12 aktiva fönster om 0,25 s, totalt 3 s aktiv signal.
   Korta pauser mellan repetitioner går bra; det kan därför ta mer än 3 s.
5. Statusen ändras till **Referens klar**. Referensen låses och mätaren börjar följa
   amplitudförändringen. Ingen manuell bekräftelse krävs.

Mätaren använder medianvärden från de aktiva fönstren, samma filter som valts i
livevyn och en utjämnad relativ amplitud. Den beräknas på servern från varje nytt
signalfönster, oberoende av webbläsarens uppdateringshastighet. Referensen flyttas
inte upp när amplituden ökar. Vid vila visas ingen bedömning.

Om mätaren stannar på **Samlar aktiv referens** kan vilonivån ha mätts under
kontraktion eller signalen vara för svag/brusig. Välj **Kalibrera om automatiskt**,
slappna av under vilofasen och börja sedan övningen. Statusfältet visar också om
signalen ligger nära ADC-gränsen eller innehåller stora tidsluckor.

Automatik kan inte avgöra om en signal verkligen kommer från en utvilad muskel,
eller skilja alla rörelseartefakter från aktivitet. Jämför samma övning, belastning
och elektrodplacering. Särskilt dynamiska curls kan ge amplitudförändringar genom
hela repetitionen. Detta är en stabilare programfunktion, inte en fysiologisk validering.

### Vad betyder skalan?

`ratio = 0.5 × (RMS / RMS_ref + MAV / MAV_ref)`

Förhållandet jämnas ut med en vikt på 0,25 för varje nytt 0,25 s-fönster.
`index = begränsa(100 × (utjämnat_ratio - 1), 0, 100)`

- 0: samma eller lägre amplitud än referensen.
- 50: ungefär 50 % högre relativ amplitud efter utjämning.
- 100: minst en fördubbling efter utjämning.

Detta är ett illustrativt amplitudindex, **inte procent muskeltrötthet eller en
validerad klassificering av trött/inte trött**. RMS/MAV kan också öka med kraft,
rörelse och brus. Inga universella kliniska gränsvärden används.

Tekniska aktivitetsgränser är heuristiska: aktiv referens kräver filtrerad pin-RMS
over det högsta av 3 mV och 2,5 × vilonivån. Vid senare vila används en lägre
aktivitetsgräns. Ett konstant brus kan inte pålitligt skiljas från EMG enbart
med dessa mått. Använd aldrig indexet som bevis på mätningens kvalitet.

## När inspelningen avslutas

Samma flöde gäller när tiden går ut och när du klickar **Sluta spela in**:

1. Programmet förbereder analysen och öppnar **Vill du spara inspelningen?**
2. Ange namn, valfri anteckning och egen trötthetsetikett.
3. Välj **Spara i Mina analyser** eller **Nej, kasta**.
4. När du sparar öppnas **Mina analyser** direkt, listan uppdateras och den nya
   mätningen markeras och visas.

Före ditt val finns den nya inspelningen endast i serverns arbetsminne; inga
inspelningstexter eller analysfiler skrivs automatiskt. Kasta skriver inga filer.
Ladda om webbsidan går bra: frågan finns kvar. En ny inspelning kan inte skriva
över en inspelning som väntar på ditt beslut.

Om du stänger Python-servern innan du väljer Spara går osparad inspelning förlorad.
Vid fel under sparandet ligger inspelningen kvar i minnet så att du kan försöka igen.
Ett nätavbrott eller en för kort/ojämn signal kan hindra analysen. Om data finns
får du ändå välja att spara dem; posten märks då tydligt om endast rådata finns.
Utan mottagna sampel visas i stället ett felmeddelande eftersom inget kan sparas.

## Vad sparas?

I `data/` bredvid server.py, först efter att du väljer Spara:

- `<id>_raw.txt`: ursprungliga tider i sekunder och ADC-pinspänning i mV, med bias.
- `<id>_signal.txt`: korrigerad signal om analysen kunde genomföras.
- `<id>.json`: analys, namn, kommentarer, inställningar, automatisk referens och
  indikatorns tidsserie efter kalibreringen (inklusive vila som tomma indexvärden).

CSV-export i gränssnittet exporterar tid, RMS och MAV. Filimport fortsätter att
analyseras och sparas när du klickar **Analysera & spara**. Mina analyser visar
även tidigare JSON-analyser som webbprogrammet har sparat.
Radera analys i gränssnittet tar bort JSON-posten; redan sparade signalfiler behålls.
Kopiera hela `data/` för att säkerhetskopiera.

## Prova utan ESP32

Klicka **Prova automatisk live-demo**. Den kör i 14 s och innehåller:

- 0–3 s: svag simulerad vilosignal.
- 3–7 s: aktiv testsignal för referensen.
- Därefter: ökande amplitud som får mätaren att stiga.

Demot går genom samma mottagningsbearbetning, kalibrering och sparfråga som en
riktig inspelning, men provar inte det fysiska kortet eller TCP-länken.
Välj Kasta om du inte vill behålla den syntetiska inspelningen.

För separat TCP-test kör du `python3 simulate_esp32.py` i en andra terminal med
.venv aktiverad. Välj IP **127.0.0.1**, port **5000**, bias **1.65**, gain **100**
och minst 14 sekunder i livevyn. Simulatorn börjar också med vila, därefter aktivitet
och ökande amplitud. Byt tillbaka till kortets IP och gain efteråt.

## ESP32-C6 Zero och Wi-Fi

Hela anslutningsguiden finns också under **Koppla ESP32** i webbsidan.

Öppna filen 'esp32_emg.io' i Arduino IDE eller PlatformIO.

I Arduino IDE installerar du **esp32 by Espressif Systems**, stabil version 3.3.5
eller senare. Vid behov lägg till följande i Additional Boards Manager URLs:

`https://espressif.github.io/arduino-esp32/package_esp32_index.json`

Välj **Waveshare ESP32-C6-Zero**, korrekt USB-port och **USB CDC On Boot → Enabled**.
Öppna `esp32_emg/esp32_emg.ino`, som redan är inställd på Wi-Fi och GPIO1:

```cpp
#define TRANSPORT 0
#define EMG_ADC_PIN 1
```

Behåll `USE_ROUTER = false`. Ladda upp utan kroppselektroder anslutna. Serial
Monitor (921600 baud) ska efter RESET visa IP 192.168.4.1, TCP-port 5000 och fs=2000.

Anslut datorns Wi-Fi till **ESP32-EMG**, standardlösenord **emgsetup2026** (eller det
du själv angivit i firmware). Nätet saknar internet, vilket är normalt. Hemsidan
har inga externa CDN-beroenden. Välj ESP32-adress 192.168.4.1, port 5000 i livevyn.
Webbsidans adress 127.0.0.1:8000 är datorns egen adress, inte ESP32:s.

C6 har BLE men inte Bluetooth Classic SPP. Webbversionen använder Wi-Fi; välj
inte TRANSPORT 2 för C6. Du behöver inte para kortet med datorn via Bluetooth.

| Kretsen | ESP32-C6 Zero |
|---|---|
| ESP32 Input, efter R4 | GPIO1 (märkt 1) |
| De två 3.3V-märkningarna | 3V3 |
| Signaljord, batteriernas mittpunkt | GND |

Koppla inte den negativa batteriledningen till ESP32:s GND. Förstärkarna behöver
sin separata positiva/negativa matning. Kontrollera hela ADC-signalens spänningsområde
före anslutning. Använd avsedd strömmatning, inte 9 V direkt till 3V3.
Vid kroppsmätning används kontrollerad batterimatad utrustning. Låt handledaren
kontrollera elsäkerheten; nätansluten USB/laddare/oscilloskop kräver lämplig isolation.

## Bias, gain och filter

ESP32 skickar tid i mikrosekunder och uppmätt ADC-pinspänning i mV inklusive bias.
Python beräknar `(pin_mV - 1000 × bias_V) / gain`. Enligt schemat är startvärdena
bias 1,65 V och nominell gain 101,4, men mät de verkliga värdena. Filtren gör
förstärkningen frekvensberoende; division med 101,4 återställer inte exakt hela
spektrumet vid elektroderna. U2:s inversion ändrar inte RMS/MAV.

Automatisk bias (valfri kryssruta) betyder DC-skattning och är en annan sak än
indikatorns automatiska aktivitetsreferens. Referens och live-RMS/MAV tar bort
lokalt medelvärde och använder samma valda bandpass/notch i 250 ms-fönster.
Slutanalysen filtrerar hela inspelningen och kan skilja sig något vid kanterna.

C6 har vid hög attenuation ett angivet mätområde upp till 3,3 V. För indikatorn
används försiktiga närgränser 20–3280 mV; dessa är mjukvarukontroller, inte skydd
eller exakta klippgränser. Den tidigare gränsen 2450 mV kunde avvisa giltig C6-data.
Mjukvara kan inte reparera analog klippning eller ersätta ett anti-aliasfilter.

## Felsökning och verifiering

- Ingen sida: kontrollera att `python3 server.py` körs och att port 8000 är ledig.
- Ingen Wi-Fi-data: kontrollera datorns nätverk, IP/port och kortets strömförsörjning.
- Ingen aktiv referens: börja i vila, sedan aktiv kontraktion; läs kalibreringsstatus.
- Spara fungerar inte: läs meddelandet i dialogen och kontrollera skrivbehörighet/diskutrymme.
- Uppdateringen syns inte: stoppa gamla servern, byt ALLA fyra kodfilerna och ladda om sidan.

Kör `python3 -m unittest -v test_web.py` för tester av automatisk kalibrering,
pauser, jitter, ADC-gränser, tidsstyrt/manuellt stopp, sparande, kasta, fellägen
samt befintlig filanalys, trötthetsetiketter och radering. `node test_ui.cjs` testar
dialoghändelser, radmarkering, etiketter samt radering/avbryt/fel med en DOM-stub.
Node behövs inte för att använda sidan. JavaScript syntaxkontrolleras också.

Ingen fysisk ESP32 eller verklig EMG-signal har testats här. DOM-stubben är inte
visuell webbläsarverifiering. Ursprungliga firmware behöver verifieras på din utrustning.

Källor:
- https://docs.waveshare.com/ESP32-C6-Zero/Arduino
- https://developer.espressif.com/blog/2025/08/adc-performance/
- https://pmc.ncbi.nlm.nih.gov/articles/PMC7747893/
