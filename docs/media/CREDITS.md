# Media credits

Everything in the videos under `docs/media/` is either made for this project, recorded from the live app, or used under a licence that allows it with no fee.

## Voice

- **Narration:** [Chatterbox TTS](https://github.com/resemble-ai/chatterbox) (Resemble AI, MIT licence), reading with its own built-in synthetic voice (`video/narration/voice-ref-bright.wav` is Chatterbox's built-in voice; no real person's voice is cloned).
- **The Hindi alert** heard in the demo is the real output of Amazon Polly (voice Kajal, hi-IN) for a Gohar alert on the live stack, copied from its S3 bucket by `video/live.mjs`.

## Music

- "Pukaar bed": synthesised for these videos by `video/narration/music.py` (pads, sub-bass and a sparse arpeggio, generated from code; no samples). Original work, dedicated to the public domain under CC0 1.0.

## Stock footage

Pexels License (https://www.pexels.com/license/): free to use, no attribution required; credited anyway. Clip list (written from `video/footage.json`):

- `timelapse` (used in the demo): opener: time-lapse of storm clouds rolling over forested Himalayan ridges, by Ankit Verma. https://www.pexels.com/video/mountain-timelapse-17791400/
- `rain`: heavy monsoon rain over houses on a wooded hillside, by Mody Agyao Jr.. https://www.pexels.com/video/video-of-heavy-rainfall-from-roof-top-5091073/
- `river` (used in the demo): swollen, muddy river in full flood; cropped in to keep the sluice gates out of frame, by Sanjeewa Wijebandara. https://www.pexels.com/video/rushing-flood-6182356/
- `valley`: aerial: Himalayan valley with a river and a village on both banks, by Tauseef Kazmi. https://www.pexels.com/video/scenic-aerial-view-of-mountain-valley-village-33838656/
- `village` (used in the demo): aerial: hill village, houses on a terraced green slope, by Soumyadeep Das. https://www.pexels.com/video/scenic-aerial-view-of-mountain-village-32213666/
- `night`: night: moon behind clouds, lights of a hillside settlement below, by Betül Hökelek. https://www.pexels.com/video/moon-behind-clouds-over-city-13208093/
- `damage` (used in the demo): aerial: fresh landslide scar beside a hill road (9 s), by NGUYỄN THÀNH NHƠN. https://www.pexels.com/video/aerial-view-of-rural-landscape-with-road-35542240/
- `phone`: hands on a simple keypad phone (hands only for the first ~7 s, then a profile), by KoolShooters. https://www.pexels.com/video/a-woman-using-an-old-cell-phone-8102790/
- `elder`: an older man calmly taking a phone call (6 s), by Kampus Production. https://www.pexels.com/video/man-talking-on-the-phone-6306260/
- `forecast` (used in the demo): satellite view of storm systems over Earth (stands in for a forecast), by Colin Jones. https://www.pexels.com/video/view-from-satellite-on-earth-10409075/
- `office`: control room: operators at desks under a wall of monitors and maps, by Kiwi and Camera. https://www.pexels.com/video/high-tech-control-room-with-traffic-monitoring-38779099/
- `dawn`: close: morning light over Himalayan foothills, river and town below, by Nitin Khajotia. https://www.pexels.com/video/rishikesh-16232800/

## Screens

All app screens are recorded from the live site (https://main.d15r7ktz99l46x.amplifyapp.com) with Playwright. The 3D valley on the landing page and the 3D map use AWS Open Data Terrain Tiles (Mapzen terrarium, `s3://elevation-tiles-prod`); map data © OpenStreetMap contributors.
