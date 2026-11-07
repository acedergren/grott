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
- Protokoll som varken är 05 eller 06 kraschade tidigare på ett odefinierat CRC-värde (`UnboundLocalError`) och posten släpptes. README säger att äldre omvandlare bara längdkontrolleras. Det är nu längdkontroll utan CRC. Ogiltig längd och trasig CRC på 05/06 avvisas fortfarande.
- Accept-loopen vaknar var 0,5 sekund så att den går att stoppa. En ensam proxy använder egna socketlistor i stället för klassvariabler.
- Blockerade kommandon loggar posttyp och kommando-id, inte längre hela kroppen.
- Grottserver har en egen kopia av dekrypteringen och kan glida isär.

## Andra delen: granskning och Compose

PR 1 är mergad (`13577c05666b3cfc64d924d4b2a1290dcde4c040`). Den här delen ligger på en ny gren från forkens `master`. Ingen merge och ingen driftsättning.

### Vad som rättades

- Logger-sidan sätter ihop TCP-strömmen till hela ramar. En delad T06NNNN-post (100 byte, sedan resten) vidarebefordras och publiceras. Två hopslagna poster ger två MQTT-meddelanden. En ofullständig ram vidarebefordras inte och loggas som `discarded incomplete frame` utan payload.
- Svar från upstream är fortfarande en `recv` i taget. Ett kort ACK klistras inte ihop med nästa post. Det är det befintliga molnbeteendet.
- `ggrottport` och `gminrecl` från miljön blir heltal. Tidigare blev `ggrottport=15279` en sträng och `bind` kastade `TypeError`.
- MQTT-fel fångar `Exception`, inte `BaseException`. Konfigurerat lösenord, PVOutput-nyckel och Influx-token/lösenord maskas i feltexten. paho-mqtt 2.2 `publish.single` använder redan `CallbackAPIVersion.VERSION2` internt. Ett lösenordsskyddat Mosquitto på `127.0.0.1:18884` tog emot JSON, och feltexten innehöll inte lösenordet.
- Protokoll 04 med giltig längd kraschar inte längre. Tidskommandot `001f` på okrypterad post jämförs fortfarande med råa byte mot strängen `"001f"` och förblir blockerat. Protokoll 05 använder kommandot vid klartextbyte 18. Protokoll 06 använder byte 38. `0011` släpps bara när `noipf` är satt.
- Den levererade isolerade Compose-filen har `networks.isolated.internal: true` och en hälsokontroll mot `127.0.0.1:5279`. Lyssningsadressen är oförändrad `127.0.0.1`. Inga host-portar publiceras.

### Tre skilda utfall

1. Avkodare och MQTT: pytest och den tillfälliga MQTT-överlagringen publicerar `pvpowerout` 5051, tid `2021-02-09T12:14:10`, enhet `QMB2823261`.
2. Proxy med fejkad upstream: hela exempelposten når en lokal TCP-peer. Det är inte Growatts server.
3. `noforward`: posten tas emot och dekrypteras, men ingen upstream öppnas och loggern får inget serversvar. Två nya TCP-sessioner mot samma process bevisar inte en färdig logger-session.

### Kommandon som faktiskt kördes

```bash
/tmp/grott-venv/bin/pytest tests -q
sudo docker build -f docker/dockerfile -t grott:local .
python3 scripts/verify_isolated_compose.py
```

Pytest: `24 passed in 23.90s`.

Image: `grott:local` är `linux/amd64`, id `sha256:9bf2c50d6cec6100ba8a5ac1ed9332ec837a74460668390401b9ad010e0ab502`. Basen i receptet är `python:3.12.16-slim` med digest `sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54`. Bygget använde den äldre buildern. Buildx 0.30.1 installerades efteråt och ändrade inte den byggda imagen.

Docker Compose `2.40.3+ds1-0ubuntu1~24.04.1`. Dockerd startades med `--iptables=false` och `vfs`.

Isolerad profil, projekt `grottisolated`:

- hälsokontroll `healthy`
- `/proc/net/tcp` visar `0100007F:149F`, alltså `127.0.0.1:5279`, inte `0.0.0.0`
- `NetworkSettings.Ports` är `{}` och `docker port` är tom
- anslutning från värden till `127.0.0.1:5279` ger `Connection refused` (errno 111)
- anslutning inifrån containern till `1.1.1.1:443` ger `Network is unreachable` (errno 101)
- routingtabellen har bara bryggnätet `172.18.0.0/16`, ingen default-route
- två injicerade sessioner gav två rader `Growatt packet received` och två `Growatt data decrypted V2`, med peer `noforward`
- ingen rad `MQTT message message sent` och ingen `forward error`

Injektionen gjordes med `docker exec` mot loopback i samma nätverksnamespace. Compose-filen ändrades inte till `0.0.0.0`.

Den tidiga utskriften `Command line parameters processed` visar fortfarande standardvärden innan ini och miljövariabler applicerats (`verbose True`, `nomqtt False`). Det är inte den effektiva profilen. Körningen efteråt är `noforward` och kommando-blockering.

### MQTT-överlagring, bara test

`docker/docker-compose.isolated-mqtt-test.yml` är inte den levererade profilen. Den slår på MQTT mot Mosquitto 2.0.18 med ett efemärt lösenord under `/tmp/grott-isolated-verify`. Katalogen togs bort efter körningen. Lösenordet skrevs inte i loggen; `gmqttpassword_file` maskas som `**secret**`.

På den här arbetsytan tar en TCP-handshake mellan två containrar på ett internt bryggnät time out (`iptables=false`). Därför delar broker och watcher Grott-containerns nätverksnamespace och använder `127.0.0.1`. Det är en testuppställning. Den levererade profilen har ingen broker.

Resultat: två MQTT-meddelanden, `device` `QMB2823261`, `time` `2021-02-09T12:14:10`, `pvpowerout` 5051, `buffered` `no`. `noforward` kvar. Egress till `1.1.1.1:443` fortfarande errno 101. `docker port` tom. Imagens `EXPOSE 1883` syns som `1883/tcp: null` och är inte en publicerad host-port.

### arm64 och ARM32

`qemu-user-static` 8.2.2 finns. `binfmt_misc` var tom tills den monterades om och `qemu-aarch64` registrerades. Direkt `qemu-aarch64-static` mot den officiella `python:3.12.16-slim` för `linux/arm64` (image `sha256:3617028275c0b0ffabe98f1d7eaa6b85624af2f457678f185c307ff3c1d31ae6`) skrev `aarch64` och `3.12.16`.

En arm64-image av Grott byggdes inte. `libscrc==1.8.1` har inget aarch64-hjul; pip hämtade källkoden. Slim-imagen har ingen kompilator. Bygget av det hjulet föll dessutom på att pip-subprocessen tappade `-c` och försökte öppna filen `//install`. Exempelposten avkodades därför inte på arm64. ARM32 är fortfarande inte byggd.

### Fortfarande öppet

- Ingen återanslutning mitt i en ström, och `noforward` ger ingen logger-ACK.
- MOD 10KTL3-XH, ShineWiFi-X och batteri är overifierade.
- Sniff är okörd.
- Verbose kan fortfarande skriva ut raminnehåll.
- Upstream saknar LICENSE. Den här forken lägger inte till en.
