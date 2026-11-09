# Hao Deng Mesh (lokal) für Home Assistant

Lokale Steuerung von **Hao-Deng- / Zengge-Bluetooth-Mesh-Lampen** (App „Hao Deng“, `com.zengge.telinkmeshlight`) direkt aus Home Assistant – **ohne Hao-Deng-App, ohne WLAN-Bridge, ohne Cloud im Betrieb**.

## Funktionsweise

```
Home Assistant ──(Bluetooth oder ESPHome-Proxy)──▶ eine Lampe ──(Mesh)──▶ alle anderen Lampen
```

* Die Lampen bilden ein verschlüsseltes Telink-Bluetooth-Mesh. Eine Verbindung zu **irgendeiner** Lampe reicht, das Mesh leitet Befehle und Statusmeldungen weiter.
* Die Integration wählt automatisch die Lampe mit dem besten Signal – über den Bluetooth-Adapter des HA-Hosts **oder** über beliebige ESPHome-Bluetooth-Proxys.
* Statusänderungen (auch aus App, Fernbedienung oder Wandschalter) kommen per Push an.
* Die Hao-Deng-Cloud wird **nur bei der Einrichtung** genutzt, um Mesh-Name, Mesh-Passwort und Lampenliste herunterzuladen. Dein App-Login wird **nicht** gespeichert.

## Voraussetzungen

* Home Assistant 2025.8 oder neuer
* Bluetooth in Reichweite mindestens einer Lampe:
  * **VM auf Synology / Proxmox:** Empfohlen ist ein **ESPHome-Bluetooth-Proxy** (ESP32, ca. 5–10 €), siehe [`esphome/bluetooth-proxy.yaml`](esphome/bluetooth-proxy.yaml). Funktioniert unabhängig davon, wo HA läuft.
  * Alternativ ein USB-Bluetooth-Stick, der an die VM durchgereicht wird (Proxmox: ja, Synology VMM: nein).
* Die Lampen müssen einmal mit der Hao-Deng-App eingerichtet worden sein.

## Installation

### Über HACS (benutzerdefiniertes Repository)
1. HACS → ⋮ → *Benutzerdefinierte Repositories* → URL dieses Repos, Kategorie *Integration*.
2. „Hao Deng Mesh (local)“ installieren, Home Assistant neu starten.

> Hinweis: Ist das Repository privat, kann HACS es nur laden, wenn der bei HACS hinterlegte GitHub-Zugang Zugriff darauf hat. Sonst manuell installieren.

### Docker-Installation mit Git (empfohlen für Updates)
Einmalig einen Deploy Key (nur Lesezugriff auf dieses Repo) auf dem Host anlegen und das Repo klonen, danach genügt für jedes Update:

```bash
~/haodeng-ha/scripts/update-ha.sh
```

Das Skript holt die neueste Version, kopiert sie nach `custom_components/` und startet den Container neu. Pfade lassen sich über `HA_CONFIG`, `HA_STACK` und `HA_SERVICE` anpassen.

### Manuell
Ordner `custom_components/haodeng_mesh` nach `/config/custom_components/haodeng_mesh` kopieren (z. B. per Samba- oder File-Editor-Add-on) und HA neu starten.

## Einrichtung

1. *Einstellungen → Geräte & Dienste → Integration hinzufügen → „Hao Deng Mesh“*.
2. App-Benutzername, Passwort und Server-Region (Deutschland = **Europa**) eingeben.
3. Bei mehreren Orten den gewünschten Ort wählen. Weitere Orte als zusätzlichen Eintrag hinzufügen.

**Neue Lampen in der App hinzugefügt?** Eintrag → ⋮ → *Neu konfigurieren* → erneut einloggen. Lampenliste und Zugangsdaten werden aktualisiert, Entitäten bleiben erhalten.

### Gruppen
Gruppen aus der Hao-Deng-App werden als eigene Licht-Entitäten angelegt. Ein Befehl an die Gruppe geht als **ein** Mesh-Befehl an die Gruppenadresse – alle Lampen schalten exakt gleichzeitig (wie mit der Fernbedienung).
Gruppen in der App geändert? → *Neu konfigurieren*.

### Optionen
* **Wärmstes / kältestes Weiß (K):** Farbtemperaturbereich der Lampen (Standard 2700–6500 K).
* **Farbtemperatur umkehren:** Falls „warm“ und „kalt“ vertauscht sind.

## Entitäten

| Entität | Beschreibung |
|---|---|
| `light.*` | Je Lampe: Ein/Aus, Helligkeit, Farbe (RGB), Farbtemperatur |
| `light.<gruppenname>` | Je Gruppe aus der App: ein Mesh-Befehl schaltet alle Mitglieder gleichzeitig. Zustand = eingeschaltet, sobald ein Mitglied an ist |
| `binary_sensor.*_mesh_verbindung` | Diagnose: Verbindung zum Mesh besteht |
| `sensor.*_verbunden_uber` | Diagnose: über welche Lampe verbunden; Attribute `last_error`, `wifi_bridge_online` |
| `button.*_neu_verbinden` | Diagnose: Verbindung neu aufbauen |

## Dashboard-Karte „Hao Deng Licht“

Die Integration bringt eine eigene Karte im Stil der Hao-Deng-App mit (wird automatisch geladen, keine Ressource nötig):
Farbring (Winkel = Farbe, Abstand = Sättigung), innen Warm-/Kaltweiß, Schnellwahl-Farben, Helligkeitsregler und Ein/Aus.
Funktioniert mit jeder Lampe oder Gruppe – auch mit Lampen anderer Integrationen.

Dashboard bearbeiten → *Karte hinzufügen* → „Hao Deng Licht“, oder per YAML:

```yaml
type: custom:haodeng-light-card
entity: light.kuche
name: Küche            # optional
presets:               # optional, max. 6
  - color_temp_kelvin: 2700
  - color_temp_kelvin: 6500
  - rgb_color: [0, 0, 255]
  - rgb_color: [255, 110, 30]
    brightness_pct: 40
```

## Bridge und App weiter nutzen?

Ja, beides kann parallel weiterlaufen. Die WLAN-Bridge ist aber nicht mehr nötig und kann abgesteckt werden.
Wichtig: Die Lampen **nicht** in der App zurücksetzen oder neu koppeln – dann ändern sich die Mesh-Zugangsdaten. In dem Fall einfach *Neu konfigurieren*.

## Fehlersuche

Debug-Logging in `configuration.yaml`:

```yaml
logger:
  logs:
    custom_components.haodeng_mesh: debug
```

* **Alle Lampen „nicht verfügbar“, Sensor „Verbunden über“ leer:** keine Lampe in Bluetooth-Reichweite → Proxy näher an eine Lampe; im Proxy muss `bluetooth_proxy: active: true` gesetzt sein.
* **`last_error`: „rejected the mesh credentials“:** Lampen wurden in der App neu gekoppelt → *Neu konfigurieren*.
* Diagnose-Download (Eintrag → ⋮ → *Diagnose herunterladen*) enthält keine Passwörter und hilft bei der Analyse.

## Entwicklung

```bash
uv venv && . .venv/bin/activate
uv pip install pytest-homeassistant-custom-component pycryptodome ruff
pytest && ruff check .
```

`custom_components/haodeng_mesh/protocol/` enthält das reine Protokoll (Telink-Verschlüsselung, Befehle, Statusauswertung) ohne Home-Assistant-Abhängigkeit. Die Tests prüfen die Verschlüsselung bitgenau gegen die ursprüngliche Implementierung.

## Herkunft

Protokollwissen aus [SleepyNinja0o/home-assistant-zengge](https://github.com/SleepyNinja0o/home-assistant-zengge) (MIT, archiviert 2026), das wiederum auf [fsaris/home-assistant-awox](https://github.com/fsaris/home-assistant-awox) aufbaut. Integration vollständig neu geschrieben.
