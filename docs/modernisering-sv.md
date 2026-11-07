# Modernisering, första delen

Fork av `johanmeijer/grott` vid `fb52e2d4` (Grott 2.8.3). Körsträngens versionsnummer är oförändrat `2.8.3`. Upstream har ingen LICENSE-fil. Den här forken lägger inte till en licens och omlicensierar inte koden.

Det här är inte ett molnfritt läge. Proxy och sniff läser fortfarande de poster som är på väg till Growatts servrar. Standardläget skickar posterna vidare dit. `noforward` är ett explicit utvecklingsval.

Grottserver och det skrivbara register-API:t är orörda.

## Vad som ändrats

- Regressionstester låser exempelpaketet i `examples/grotttest.py`: dekryptering, layout `T06NNNN`, MQTT-JSON och fem skalade mätvärden.
- TCP-proxyn provas mot en fejkad upstream på loopback och en lokal Mosquitto. Avhuggna poster, trasig CRC, okänd posttyp och kommando-blockering ingår.
- Dekryptering, layout/fält, MQTT-publicering och kommando-policy ligger i egna moduler. Fältens offset, mask och JSON-form är desamma.
- Image-receptet använder Python 3.12.16 i stället för Python 3.7. Direkta beroenden är pinnade.
- Isolerad profil, `examples/profiles/isolated.ini`: externa utgångar av, skrivkommandon blockerade, lyssning på `127.0.0.1`, ingen vidarebefordran, hemligheter från fil om en utgång senare slås på. Ingen port publiceras i `docker/docker-compose.isolated.yml`.
- Fel för ogiltig eller okänd post anger protokoll, typ, längd och orsak. Själva posten skrivs inte i det meddelandet.

## Regressionsvektor

Källa: `examples/grotttest.py` (offentligt exempel, inte en live-växelriktare från den här miljön).

| Fält | Råvärde i JSON | Skalat som i de befintliga HA-mallarna |
| --- | --- | --- |
| layout | `T06NNNN` | |
| device | `QMB2823261` | |
| time | `2021-02-09T12:14:10` | paketets tidsstämpel |
| buffered | `no` | |
| MQTT-ämne | `energy/growatt` | retain false, qos 0 |
| pvpowerout | `5051` | 505.1 W |
| pvgridvoltage | `2373` | 237.3 V |
| pvtemperature | `269` | 26.9 C |
| pvenergytoday | `21` | 2.1 kWh |

Hela värdemängden ligger i `tests/vectors.py`. MQTT discovery används inte och har inte lagts till.

Exemplet är en generisk `T06NNNN`-post. Den bevisar inte firmware för MOD 10KTL3-XH, ShineWiFi-X eller batteristöd.

## Kommandon och resultat

Arbetsytan: Ubuntu 24.04, kärna 6.12.113+, värd-Python 3.12.3.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
```

Resultat: `13 passed in 25.28s`. Inga kvarvarande testfel.

Direktpinnar i `requirements.txt`:

- paho-mqtt 2.2.0
- requests 2.34.2
- libscrc 1.8.1
- influxdb 5.3.2
- influxdb-client 1.50.0
- pytest 9.2.0 (bara utvecklingsberoende)

Tester använder Mosquitto 2.0.18 på `127.0.0.1:18883`, startad av testet om porten är stängd. Ingen Home Assistant-broker, inget Growatt-konto och ingen fysisk växelriktare kontaktades. `server.growatt.com` resolvas eller öppnas inte av testen.

Image:

```bash
docker build -f docker/dockerfile -t grott:local .
```

Resultat: lyckad build. Image `sha256:e628582dca8d675e0f8ef54439e5a91d40deb03c6f4cee3b353622b96c7cbc32`. Basimage `python:3.12.16-slim` med digest `sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54`. Python i imagen är 3.12.16. Import och samma T06NNNN-avkodning kördes med `--network none`. Isolerad ini lästes i containern utan att proxyn startades.

`docker compose` finns inte i den här arbetsytan (`docker compose` gav exit 125, `docker-compose` saknas). YAML-filen parsades med PyYAML: tjänsten har ingen `ports`-nyckel. `compose up` kördes inte. Ingen container lämnades igång och ingen image pushades.

Bygget skrev en varning om att den äldre buildern är föråldrad och att BuildKit/buildx inte är installerat. Bygget gick ändå igenom. Pip meddelade att 26.3 finns; imagen uppgraderar inte pip.

`requirements.lock` är den transitiva mängd som den verifierade imagen fick. `requirements.txt` är det som Docker installerar. En senare installation kan flytta opinnade transitiva paket.

## Miljögränser

- ARM32- och Raspberry Pi-image byggdes inte. Det gamla `dockerrpi`-receptet med Python 3.7 är avstängt.
- Sniff-läge kräver råa paket och kördes inte.
- Bara ett upstream-exempelpaket finns i trädet. Övriga layouter, inklusive smartmätare och loggfält, saknar samma låsning.
- `-v` kan fortfarande skriva ut raminnehåll. De nya felraderna gör det inte.
- Ingen GitHub-workflow har lagts till.

## Kvarvarande risker

- Standardproxyn är fortfarande beroende av att Growatt-servern svarar. Utan den stängs klienten, precis som tidigare, om inte `noforward` är satt.
- `noforward` ger inga serversvar till loggern. Det är ett fångstläge för utveckling, inte drift.
- Exakt kompatibilitet med MOD 10KTL3-XH, ShineWiFi-X och batteri är overifierad.
- Protokoll som varken är 02, 05 eller 06 kunde tidigare krascha proxyn på ett odefinierat CRC-värde. De avvisas nu som ogiltiga och skickas inte vidare.
- Accept-loopen vaknar var 0,5 sekund så att den går att stoppa. En ensam proxy använder egna socketlistor i stället för klassvariabler.
- Blockerade kommandon loggar posttyp och kommando-id, inte längre hela kroppen.
- Grottserver har en egen kopia av dekrypteringen och kan glida isär.
