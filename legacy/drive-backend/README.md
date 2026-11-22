# miles-drive

API behind https://miles.bolls.dev/drive/: nearly empty MILES cars in Berlin that pay a refuelling (or charging)
credit, with the nearest likely partner station. The frontend lives in `../miles-atlas/static/drive/`.

`app.py` reads the live scraper's Postgres through the read-only role `ops_ro`, rebuilds a snapshot every 10 s and
serves it as `GET /cars` (pre-serialised, ETag). `POST /did` stores anonymous "I did it" taps in SQLite. It never
talks to MILES. Deploy: `./deploy.sh` (docker compose on host `bolls`, `/opt/miles-drive`, 127.0.0.1:8792, behind
nginx `/drive/api/`).

## Credit rules (MILES help center, read 21 Nov 2026)

| Rule | Source |
| --- | --- |
| **€5 refuelling bonus**: standard km rate (not an hourly or daily rate), tank below 25% at rental start, filled to 100%, at a partner gas station in Germany, rented in the MILES app (not a partner platform). Once per vehicle and rental. Credited automatically after the rental, valid 90 days, applied to the next trip. "Parking minutes incurred during the refueling process are compensated with the bonus." | [When do I get a bonus for refueling?](https://support.miles-mobility.com/hc/en-us/articles/360015528380-When-do-I-get-a-bonus-for-refueling) |
| **How refuelling works**: free at partner stations throughout Germany, no payment. Start it in the app ("Refueling"), confirm with PIN or Face/Touch ID, select the pump number, tap "Unlock nozzle", take the nozzle within 60 s, fill up, wait for the app to confirm. No fuel card. | [Everything about refueling](https://support.miles-mobility.com/hc/en-us/articles/360015531299-Everything-about-refueling), [How, when & where do I refuel?](https://support.miles-mobility.com/hc/en-us/articles/360015545399-How-when-where-do-I-refuel) |
| **€10 charging credit**: plugged into a partner charging station at the end of the rental, battery at 30% or lower at that time, more than 1 km driven, no hourly or daily rate. Valid 90 days, applied to the next trip. | [How do I get my credit for charging?](https://support.miles-mobility.com/hc/en-us/articles/5980672773650-How-do-I-get-my-credit-for-charging) |
| **Parking**: €0.35/min at the km rate while parking mode is on. | [Parking minutes](https://support.miles-mobility.com/hc/en-us/articles/4416991586834-Parking-minutes) |
| **Anniversary cars**: €0.59/km (`ANNIV_KM`). | [Birthday cars](https://support.miles-mobility.com/hc/en-us/articles/38958991630866-How-does-the-discount-on-our-birthday-cars-work) |

## Our assumptions (not from MILES)

- **Prices.** miles-mobility.com/de/pricing only gives "from" prices (S/M from €0.79/km + €1 unlock, Premium from
  €1.09/km + €2, L/XL from €1.29/km + €2). €0.79 is the discounted rate, so we assume €0.98/km for S/M and €1.29/km
  plus €2 unlock for everything larger. The app shows the real price before booking.
- **Saving shown in the UI** = credit − (unlock + km to the station × km price), plus 0.3 km to park after the pump, as if
  the station were a pure detour. If it is on the rider's way, the real saving is closer to the full credit.
- **Street distance** = straight line × 1.35 (`ROAD_FACTOR`); walking = straight line × 1.3 at 80 m/min (frontend).
- **Time at the pump**: about 10 min (our guess, not measured).
- **Partner stations** are not public. `tools/build_stations.py` marks Aral and TotalEnergies fuel stations, and
  chargers of operators that roam on Plugsurfing, as "likely"; everything else "unknown". Tesla Superchargers are
  dropped. Station data: OpenStreetMap (`tools/extract_stations.py`).
- **Car data**: positions and fuel/battery levels from the public MILES map, collected by the scraper every few
  minutes. A car can already be booked by the time it shows here.
- `done_today` in `/cars` (rides that went from <25% to ≥95% fuel) is an inference from map data and also counts
  MILES crew refuels; the frontend no longer shows it.
