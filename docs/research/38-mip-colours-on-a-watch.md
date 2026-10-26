# 38 — The 64 MIP colours on a real watch

**Question.** Research 37 picked the 27 colours a `choices: any` colour
setting offers from a *model* of a reflective MIP panel. It left one
assumption open: whether a channel's `55` and `AA` reflect ⅓ and ⅔ of the
light (linear area steps), or step like a monitor, in which case `55` is
nearly as dark as `00`. Its probe face draws all 64 on a watch, and the user
photographed it. What do the photos say about the model, and about the
list?

**Short answer.**

- **The steps are linear, as the model assumed.** In all three photos, the
  model with linear steps orders the swatches by lightness far better than
  monitor-like steps (§3). `555555` reads mid-gray (L\* 62 against the
  panel's white; linear predicts 67, monitor-like 42). The step assumption
  is now VERIFIED on a fēnix 8 Solar, to the extent a phone photo can show
  it.
- **The gamut sits inside the bracket 37 tested, near its narrow end.** The
  photo's colours are 1.27 times as saturated as the datasheet panel (7.7%
  NTSC) and 0.73 times the `wider` one (23%). That matches a gamut of about
  12.5% NTSC, and a phone's colour boost makes that an upper bound (§4).
- **The rules hold.** Pastels are the palest and grayest group, muted mixes
  and dark colours come next, and the colours the list keeps are the most
  saturated (§5).
- **The deduplication is the weak spot.** On the watch, the green–cyan
  corner of the list is crowded. `green`, `malachite`, `pigment_green`,
  `aqua` and `azure_radiance` are 2 to 7 apart in the photos, below the
  threshold that picked them. `malachite` is the one colour that every
  measurement says to drop (§6).
- **The backlight changes the picture** (§7). In room light it adds a cool
  cast. Yellows and oranges go peach, reds go pink and greens go mint.
  `aqua` and `azure_radiance` merge, and so do `conifer` and
  `silver_chalice`.

Probe: `docs/research/probes/mip-colour-appearance/` (`measure.py`, the
three photos, `photos.png`).

---

## 1. The photos

The user photographed `face.yaml` (research 37 §6: the 64 in
`MIP64_NAMED`'s order, white top left and black bottom right, with a black
dot on each colour the list drops) on their fēnix 8 Solar, in office light,
on 2026-10-26:

| Photo | Backlight | Notes |
|---|---|---|
| `photo-ambient.jpg` | off | taken at an angle; the panel's own black is dark gray |
| `photo-backlight-1.jpg` | on | some glare along the top edge |
| `photo-backlight-2.jpg` | on | |

The files are crops of the originals around the screen. A phone camera is
not a colorimeter: it applies an unknown tone curve, boosts contrast and
saturation, and balances white for the whole scene. The tests below are
built to survive that. The step test uses only the *order* of lightness,
which any monotone tone curve keeps. The colour comparisons are relative,
inside one photo, against that photo's own white swatch.

Office light is not the light a MIP panel is designed for: it is brightest
outdoors (research 37 §1). The photos say how the colours relate to each
other, not how bright the panel is in the sun.

## 2. Reading the swatches

`measure.py` maps the face's 173 px grid onto each photo with a homography
through the grid's four corners, found by hand. Each swatch is the median
of a ring of points inside it, clear of its edge and of the 6 px dot. The
sample points were drawn over each photo and checked by eye before any
numbers were read.

![each photo's 64, balanced to its white swatch, beside the datasheet model and a monitor](probes/mip-colour-appearance/photos.png)

*`photos.png`, left to right: the ambient photo, the two backlit photos (each
scaled in linear light so its white swatch draws white), the model's
`datasheet` panel, and a monitor. The ambient photo and the datasheet
model look alike: pale, low in chroma, with the middle steps light.*

## 3. The steps

The two step models disagree on the lightness order of many pairs. Take
`555555` and `00AA00`: with linear steps the gray is lighter, and with
monitor-like steps the green is. For every such pair whose camera
lightness differs by more than 3%, `measure.py` checks which order the
photo shows:

| Photo | Linear wins | Monitor-like wins | Too close | Kendall τ, linear / monitor-like |
|---|---|---|---|---|
| ambient | 116 | 47 | 16 | 0.747 / 0.677 |
| backlight 1 | 129 | 35 | 15 | 0.795 / 0.694 |
| backlight 2 | 144 | 22 | 13 | 0.822 / 0.694 |

The minority votes are what uneven light across the screen, glare and
viewing angle produce: the white swatch sits in a corner and black in the
opposite one.

Fitting the two middle steps freely gives the step values whose predicted
order best matches each photo. The best fits are `55` at 0.28 to 0.36 and
`AA` at 0.72 to 0.82, against ⅓ and ⅔ for area steps and 0.09 and 0.40
for monitor-like ones. The fit is loose. Within 0.01 of the best τ, `55`
spans 0.16 to 0.44 and `AA` 0.62 to 0.98. It excludes monitor-like steps
in every photo, though, and its centre is close to area steps. `AA` may
reflect a little more than ⅔.

The grays in the ambient photo, as L\* against its white:

| | `000000` | `555555` | `AAAAAA` | `FFFFFF` |
|---|---|---|---|---|
| photo | 35 | 62 | 94 | 100 |
| model, linear steps | 24 | 67 | 86 | 100 |
| model, monitor-like steps | 24 | 42 | 71 | 100 |

Black is lighter than the model's 25:1 floor. That is expected of a photo
taken through glass in a lit room, and it is also how the panel looks.

## 4. The gamut

`measure.py` compares each photo's chroma (against its white) with the
model's, colour by colour, and finds the gamut whose median chroma matches:

| Photo | Chroma vs `datasheet` (7.7%) | vs `wider` (23%) | Matching gamut |
|---|---|---|---|
| ambient | 1.27× | 0.73× | 12.5% NTSC |
| backlight 1 | 1.43× | 0.82× | 15.5% NTSC |
| backlight 2 | 1.50× | 0.85× | 17.0% NTSC |

Phone cameras raise saturation, so the panel's true gamut in ambient light
is probably at or below 12.5%. Research 37 tested 7.7% and 23% so that its
conclusions would not rest on one module. Garmin's panel falls between the
two.

## 5. The rules

Mean L\* and C\* of each of `choose.py`'s groups, against the photo's white:

| Group | ambient L\* / C\* | backlight 1 | backlight 2 |
|---|---|---|---|
| pastel | 97 / 9.9 | 99 / 8.1 | 102 / 9.3 |
| muted | 77 / 12.9 | 89 / 15.6 | 93 / 16.6 |
| dark | 48 / 12.2 | 65 / 31.3 | 70 / 30.5 |
| brown/olive | 79 / 24.2 | 89 / 20.0 | 95 / 25.0 |
| the rest (where the 27 come from) | 74 / 26.2 | 87 / 30.1 | 89 / 31.6 |

(An L\* above 100 is a swatch the camera saw brighter than the white one,
which sits in a corner.)

- **Pastels are off-white**: the palest group and the least colourful, in
  every photo. VERIFIED.
- **Muted mixes are gray**: half the chroma of the rest, in every photo.
  VERIFIED.
- **Dark colours are dim and gray in ambient light** (L\* 48, C\* 12).
  VERIFIED. Under the backlight they keep their own hues and gain chroma
  (C\* 26 to 45 for `maroon`, `navy`, `mosque`, `tyrian_purple`). The
  mechanism is UNVERIFIED. One possibility is that the backlight's window
  does not split 2:1 the way the reflective electrode does. They stay much
  darker than the rest, and the rule is about ambient light, where a MIP
  face is read most.
- **Brown and olive** are as colourful as the rest by chroma. They were
  dropped for their hue, on preference evidence (research 37 §4), not for
  chroma, and the photos neither support nor contradict that.

## 6. The list

The closest pairs among the 27, as CIEDE2000 between photo colours:

| Photo | Closest kept pairs |
|---|---|
| ambient | malachite/pigment_green 3.5, white/silver_chalice 4.6, green/malachite 5.7, web_orange/texas_rose 6.6, electric_indigo/indigo 7.0, aqua/pigment_green 7.2, aqua/azure_radiance 7.3 |
| backlight 1 | aqua/azure_radiance 3.4, aqua/pigment_green 3.8, green/malachite 4.2, white/silver_chalice 5.1, malachite/medium_aquamarine 5.4 |
| backlight 2 | aqua/azure_radiance 1.9, malachite/pigment_green 4.1, conifer/silver_chalice 4.4, web_orange/texas_rose 5.5, aqua/pigment_green 6.1, green/malachite 6.6 |

For scale: across all the candidate pairs, a photo's ΔE runs at about 0.84
of the `wider` model's, so 37's threshold of 9 corresponds to about 7.5
here. Re-running `choose.py`'s deduplication on each photo's colours at that
threshold:

| Photo | Drops from the 27 | Adds |
|---|---|---|
| ambient | azure_radiance, indigo, malachite, pigment_green, conifer, texas_rose | bright_red, bright_green, jazzberry_jam, spring_bud, cornflower_blue |
| backlight 1 | azure_radiance, malachite, pigment_green, pink_flamingo, medium_aquamarine | midnight_blue, spring_bud, bright_green |
| backlight 2 | web_orange, azure_radiance, malachite, pigment_green, pink_flamingo, texas_rose, medium_aquamarine | bright_green, baby_blue, spring_bud |

A second route avoids the camera's colour rendering entirely: rerun
`choose.py` on the model itself with the gamut of §4. At 12.5% NTSC it
drops web_orange, electric_violet, indigo, malachite, medium_purple, conifer
and medium_aquamarine, and adds screamin_green. At 15.5 to 17% it drops
only web_orange and indigo (and electric_violet at 15.5%).

What the two routes say together:

- **`malachite` goes in all three photos and in the 12.5% model run.**
  It sits between `green` and `pigment_green`, and the pair
  research 37 named as its test, green/malachite, is 4.2 to 6.6 in the
  photos.
- **`indigo`, `pigment_green` and `azure_radiance` go in several runs.**
  `pigment_green` and `azure_radiance` go in every photo but in no model
  run, and `indigo` the other way round.
- **The adds disagree.** `bright_green` and `spring_bud` come back in every
  photo but never in the model. A camera renders a yellow-green from an
  LCD's primaries unreliably (its sensors do not see colour the way the eye
  does), so the photos alone are not a reason to add a colour.

So the membership near the threshold is not settled by either the model or
the camera. The eye on the watch is the judge, as research 37 §6 said. The
pairs to look at on `face.yaml`, by row and column:

| Pair | Where |
|---|---|
| green / malachite | row 7, columns 4 and 3 |
| malachite / pigment_green | row 7, columns 3 and 7 |
| aqua / azure_radiance | row 7, columns 1 and 5 |
| electric_indigo / indigo | row 6, columns 5 and 6 |
| web_orange / texas_rose | row 1, columns 8 and 7 |

## 7. The backlight

The backlight is a cool white compared with the office light. The white
swatch is camera sRGB (181, 200, 207) without it and (168, 212, 253) and
(151, 198, 254) with it, while the wrist around the watch keeps its colour.
In the room's light the backlit screen therefore looks blue. Balanced to
its own white (§5), colours gain some chroma, but the warm end loses it:

- `yellow` turns from hue 85° to about 62° (peach), and `web_orange` from
  61° to about 46°;
- `conifer` drops to C\* 9 to 12 and sits 4.4 from `silver_chalice`;
- `aqua` and `azure_radiance` merge (1.9 and 3.4).

The steps stay linear under the backlight (§3). A face that relies on
yellow against orange, or on a yellow-green, reads worse with the light on.
The compiler cannot change that, and the 27 are chosen for ambient light.

## 8. What this does not settle

- **One watch, one camera, office light.** The fēnix 8 Solar is the only
  panel photographed. `fr955` and the other MIP devices may differ, and
  sunlight is MIP's main case.
- **Hue.** A camera's rendering of hue from an LCD's narrow primaries is not
  the eye's, so the hues in §6 and §7 are indicative.
- **The list itself.** Research 37's 27 are unchanged by this record. §6
  names the candidates to drop and how to check them by eye.
