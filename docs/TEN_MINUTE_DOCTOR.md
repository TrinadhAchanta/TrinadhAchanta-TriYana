# Keeping the 10-minute promise

Triyana's headline is "a doctor at your door in 10 minutes". The app keeps the promise honest: it only promises 10 minutes when an online doctor is close enough, and otherwise shows the real wait. Making the promise true most of the time is an operations job more than a software one.

## How the app decides

- Time to the door = about 2 minutes to accept and pass the live face check, plus the drive.
- The drive is estimated from straight-line distance × 1.3 at 22 km/h city speed. In practice that means a doctor needs to be within roughly **2 km** of the patient.
- The promise length is `TRIYANA_PROMISE_MIN` (default 10).
- The face check before every visit stays: it is part of the 2 minutes, not skipped to save time.

## What it takes in a real city

- **Doctor density.** With a ~2 km reach, each doctor covers about 12 km². A launch area of 50 km² needs at least 4 to 5 doctors online at all times, and more at peak hours (evenings, Monday mornings) because a doctor on a visit is off the map for 30 to 45 minutes.
- **Doctor hubs.** Quick-commerce apps hit 10 minutes with dark stores placed every 2 to 3 km. The equivalent is small doctor hubs (a rented room or partner clinic) where on-shift doctors wait with a kit and a two-wheeler or car with a driver.
- **Shifts, not "go online when free".** A promise needs guaranteed coverage, so on-shift doctors are paid for availability as well as per visit.
- **Start small.** Launch in a few dense neighbourhoods where the promise holds, show "10 minutes" only there, and grow area by area. The app already falls back to "nearest doctor in about N minutes" everywhere else.
- **Measure it.** Every on-demand visit records how long the doctor took to arrive (`arrived_in_s` on the live view), so the share of promises kept can be tracked per area.

## For comparison

Kyno Health, the closest look-alike, promises about 20 minutes in parts of Delhi-NCR and Bengaluru. Ten minutes is a real difference, but only if the doctor density above is in place first.
