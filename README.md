# SnitchVis

Uses PyQt6 to render videos of [snitch](https://civwiki.org/wiki/Snitch) events from [Civ](https://civwiki.org/wiki/Main_Page) servers. Written for [CivMC](https://old.reddit.com/r/CivMC).

Can also be used as a desktop application for precision scrubbing and manipulating visualization speed and direction.

Used by [SnitchVisBot](https://github.com/tybug/snitchvisbot) to render snitches from discord.

## Installation

There is a pypi package at https://pypi.org/project/snitchvis/, but I don't push updates to it because snitchvis is over the 100mb pypi limit. Therefore I recommend you install from source:

```
pip install git+https://github.com/tybug/snitchvis.git
```

Fair warning that snitchvis is currently a 144mb install, and may increase in the future. This is due to storing the tiles for CivMC's worldmap.

## Credits

Thanks to paddington_bear and lowtuff for making their terrain data publicly available.
