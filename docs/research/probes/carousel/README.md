# Carousel feasibility probe

Hand-written Monkey C backing `docs/research/07-carousel-interaction.md` §5.
**Not part of the compiler, not generated, and not built by the test suite** —
it exists so the claims in §1–§3 can be re-checked against the real compiler
rather than re-read off a doc page.

What it exercises, all in one face:

* `WatchUi.animate()` on a `WatchFace` subclass, guarded on the sleep state
  (`animate()` crashes the app in low power mode)
* `WatchUi.cancelAllAnimations()`
* `Application.Storage` round-tripping the selected index across restarts
* `WatchFaceDelegate.onPress` with `ClickEvent.getCoordinates()` partitioned
  into previous / next / launch zones — **no `onTap`**, because it fires only
  in the on-device config editor (§1a)
* `Complications.exitTo` on an array-indexed complication type

## Rebuilding it

There is no scaffold checked in; borrow one from a real build, which also
proves the probe compiles under the same flags the compiler emits:

```sh
./.venv/bin/python wfb.py build examples/slice/face.yaml
probe=$(mktemp -d)
cp -R build/slice "$probe/carousel"
cd "$probe/carousel"

rm -rf internal-mir external-mir gen runtime-lib source-* *.prg *.debug.xml
rm -f source/*.mc
cp <repo>/docs/research/probes/carousel/*.mc source/
```

Then give it an entry point (`source/CarouselApp.mc`):

```monkey-c
import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

class SliceApp extends Application.AppBase {
    function initialize() { AppBase.initialize(); }
    function getInitialView() as [Views] or [Views, InputDelegates] {
        var view = new CarouselView();
        if (WatchUi has :WatchFaceDelegate) {
            return [ view, new CarouselDelegate(view) ];
        }
        return [ view ];
    }
}
```

`monkey.jungle` needs `base.sourcePath = source` and no per-device sections;
`manifest.xml` needs `minApiLevel="4.2.0"` (`exitTo`) and the
`ComplicationSubscriber` permission. Then:

```sh
for d in fenix8solar47mm fenix8solar51mm fr955; do
    "$CIQ_SDK/bin/monkeyc" -f monkey.jungle -d "$d" -o "carousel-$d.prg" \
        -y ~/ciq/developer_key.der -w -l 3 --build-stats 0
done
```

Recorded result (SDK 9.2.0): `BUILD SUCCESSFUL` on all three, 597 B foreground
data + 785 B foreground code each — about 1 % of the 131,072 B watch-face
budget.

Making `slide` `private` instead of `public` still builds, but warns that
`animate()`'s indirect `:slide` lookup will not find it. That warning is the
reason the member is public.
