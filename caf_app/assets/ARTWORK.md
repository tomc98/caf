# Artwork provenance

AI-generated artwork created for caf using OpenAI's image-generation tool in Codex. Project artwork is distributed under the repository's MIT license, to the extent the project holds rights in it. The included font has its own license below.

## Room

`cafe.png`, `day.png`, and `night.png` are dusk, daylight, and midnight backgrounds. The final editing pass removed all clouds, stars, sun, and moon while preserving the city and interior. Dynamic sky objects are rendered by the application.

Original generation prompt:

> Use case: stylized-concept. Create production background artwork for a gorgeous cozy lo-fi pixel-art terminal café application, landscape 16:10 composition. Crisp lovingly handcrafted 16-bit pixel art, visible square pixel clusters, limited harmonious palette, no smooth vector edges or painterly smears. Front-on fixed camera looking at a quiet little Japanese-inspired coffee shop counter. Sophisticated indie game background quality, warm honey timber, deep plum shadows, muted sage plants, copper details, dusty rose plaster. Interior fills entire frame without border or interface. Upper 65 percent: central large rectangular wooden framed window, spanning x=30% to 77% and y=12% to 58%, with a single undivided pane of simple pale lavender dusk sky and distant small city buildings; absolutely no diagonal window edges. Left of window: dark wooden shelves with cream ceramic cups and books, a small neon cursive "caf" sign at upper left. Right of window: warm pendant lamp, leafy trailing plant, a small round plain analog clock high on wall. Lower 35 percent: an expansive completely EMPTY beautiful wooden countertop reaching bottom frame, with horizontal timber grain and warm highlights; room for animated coffee brewer at left-centre, sleeping cat in centre, and a vintage radio at right. Do NOT put any cat, radio, coffee brewer, coffee mug, kettle or other object on the counter, those will be animated separately by code. Small carefully drawn environmental details on walls and shelves only, warm light pools and cozy cinematic depth. Calm nostalgic lo-fi record-cover mood, exceptional composition and pixel craft. No people, no UI, no watermark. Only text is the small neon "caf" sign.

Day/night edits preserved framing and geometry, changing only the time of day and its light. The clean-sky edit requested an empty gradient sky and preservation of all buildings, mountains, cherry trees, bridge, window frame, and interior objects.

## Sprites

`clouds.png`: four separate horizontal pixel-art cloud formations in a 2-by-2 atlas on transparent RGBA. Cream highlights, lavender undersides, stepped pixel edges, varied cumulus and stratus shapes. No sky, sun, moon, stars, text, or borders. The renderer crops the atlas into sprites, tints them for local time, and moves them independently.

`miso.png`: four poses of the same chubby orange tabby on transparent RGBA, in a 2-by-2 atlas: asleep, awake and curious, stretching, and enjoying a pet. Cream muzzle and paws, green eyes, detailed ginger stripes, crisp 16-bit pixel art. The renderer selects poses and adds breathing and small tail motion.

Coffee, radio, clock, particles, celestial objects, controls, and overlays are drawn in application code.

The Silkscreen font is separately licensed under the included FONT-LICENSE.txt.
