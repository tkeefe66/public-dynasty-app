"""Tests for the FantasyPros HTML parser.

We use hand-crafted HTML fixtures that mirror the real FantasyPros page
structure so we get parser-level confidence without making live HTTP
calls.
"""

from sleeper_dynasty.api.projections import parse_fantasypros_html

# Minimal QB page mirroring the real layout: grouped header row with
# colspans, then a label row, then two data rows. The trailing FPTS
# cell carries a data-sort-value attribute for higher precision.
_QB_HTML = """
<html><body>
<table id="data">
  <thead>
    <tr>
      <td>&nbsp;</td>
      <td colspan="5"><small><b>PASSING</b></small></td>
      <td colspan="3"><small><b>RUSHING</b></small></td>
      <td colspan="2"><small><b>MISC</b></small></td>
    </tr>
    <tr>
      <th class="player-label">Player</th>
      <th><small>ATT</small></th>
      <th><small>CMP</small></th>
      <th><small>YDS</small></th>
      <th><small>TDS</small></th>
      <th><small>INTS</small></th>
      <th><small>ATT</small></th>
      <th><small>YDS</small></th>
      <th><small>TDS</small></th>
      <th><small>FL</small></th>
      <th><small>FPTS</small></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td class="player-label">
        <a href="/x" class="player-name fp-player-link"
           fp-player-name="Jalen Hurts">Jalen Hurts</a> PHI
      </td>
      <td>498.5</td>
      <td>337.1</td>
      <td>3,830.1</td>
      <td>28.6</td>
      <td>12.3</td>
      <td>120.7</td>
      <td>594.8</td>
      <td>11.7</td>
      <td>4.1</td>
      <td data-sort-value="376.901">376.9</td>
    </tr>
    <tr>
      <td class="player-label">
        <a href="/x" class="player-name fp-player-link"
           fp-player-name="Patrick Mahomes II">Patrick Mahomes II</a> KC
      </td>
      <td>540.0</td>
      <td>360.0</td>
      <td>4,200.0</td>
      <td>30.0</td>
      <td>10.0</td>
      <td>55.0</td>
      <td>250.0</td>
      <td>2.0</td>
      <td>3.0</td>
      <td data-sort-value="320.5">320.5</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


# Minimal RB page (different group ordering: rushing first, then receiving).
_RB_HTML = """
<html><body>
<table id="data">
  <thead>
    <tr>
      <td>&nbsp;</td>
      <td colspan="3"><small><b>RUSHING</b></small></td>
      <td colspan="3"><small><b>RECEIVING</b></small></td>
      <td colspan="2"><small><b>MISC</b></small></td>
    </tr>
    <tr>
      <th>Player</th>
      <th><small>ATT</small></th>
      <th><small>YDS</small></th>
      <th><small>TDS</small></th>
      <th><small>REC</small></th>
      <th><small>YDS</small></th>
      <th><small>TDS</small></th>
      <th><small>FL</small></th>
      <th><small>FPTS</small></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>
        <a href="/x" class="player-name"
           fp-player-name="Saquon Barkley">Saquon Barkley</a> PHI
      </td>
      <td>20.4</td>
      <td>105.7</td>
      <td>0.8</td>
      <td>2.4</td>
      <td>18.5</td>
      <td>0.1</td>
      <td>0.1</td>
      <td data-sort-value="20.204">20.2</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


# K page (flat layout, no group headers).
_K_HTML = """
<html><body>
<table id="data">
  <thead>
    <tr>
      <th>Player</th>
      <th><small>FG</small></th>
      <th><small>FGA</small></th>
      <th><small>XPT</small></th>
      <th><small>FPTS</small></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>
        <a href="/x" class="player-name"
           fp-player-name="Brandon Aubrey">Brandon Aubrey</a> DAL
      </td>
      <td>35.3</td>
      <td>39.8</td>
      <td>47.6</td>
      <td data-sort-value="153.335">153.3</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


# DST page.
_DST_HTML = """
<html><body>
<table id="data">
  <thead>
    <tr>
      <th>Player</th>
      <th><small>SACK</small></th>
      <th><small>INT</small></th>
      <th><small>FR</small></th>
      <th><small>FF</small></th>
      <th><small>TD</small></th>
      <th><small>SAFETY</small></th>
      <th><small>PA</small></th>
      <th><small>YDS AGN</small></th>
      <th><small>FPTS</small></th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>
        <a href="/x" class="player-name"
           fp-player-name="Houston Texans">Houston Texans</a>
      </td>
      <td>49.2</td>
      <td>14.1</td>
      <td>12.4</td>
      <td>18.3</td>
      <td>2.7</td>
      <td>1.0</td>
      <td>321.2</td>
      <td>5,067.0</td>
      <td data-sort-value="120.56">120.6</td>
    </tr>
  </tbody>
</table>
</body></html>
"""


def test_parses_qb_table():
    out = parse_fantasypros_html(_QB_HTML, "QB")
    assert len(out) == 2

    hurts = out["jalen hurts"]
    assert hurts.name == "Jalen Hurts"
    assert hurts.team == "PHI"
    assert hurts.position == "QB"
    assert hurts.stats["pass_att"] == 498.5
    assert hurts.stats["pass_yd"] == 3830.1  # comma stripped
    assert hurts.stats["pass_td"] == 28.6
    assert hurts.stats["pass_int"] == 12.3
    assert hurts.stats["rush_att"] == 120.7
    assert hurts.stats["rush_yd"] == 594.8
    assert hurts.stats["rush_td"] == 11.7
    assert hurts.stats["fum_lost"] == 4.1
    # Uses data-sort-value (higher precision than display).
    assert hurts.projected_points_ppr == 376.9

    # Suffix-stripped normalized name for Mahomes II.
    mahomes = out["patrick mahomes"]
    assert mahomes.name == "Patrick Mahomes II"


def test_parses_rb_table_different_group_order():
    # RB layout puts RUSHING before RECEIVING — confirm grouping logic
    # handles either order.
    out = parse_fantasypros_html(_RB_HTML, "RB")
    saquon = out["saquon barkley"]
    assert saquon.stats["rush_att"] == 20.4
    assert saquon.stats["rush_yd"] == 105.7
    assert saquon.stats["rush_td"] == 0.8
    assert saquon.stats["rec"] == 2.4
    assert saquon.stats["rec_yd"] == 18.5
    assert saquon.stats["rec_td"] == 0.1
    assert saquon.stats["fum_lost"] == 0.1
    assert saquon.projected_points_ppr == 20.2


def test_parses_k_table_flat():
    out = parse_fantasypros_html(_K_HTML, "K")
    aubrey = out["brandon aubrey"]
    assert aubrey.position == "K"
    assert aubrey.team == "DAL"
    assert aubrey.stats["fgm"] == 35.3
    assert aubrey.stats["fga"] == 39.8
    assert aubrey.stats["xpm"] == 47.6
    # data-sort-value=153.335, rounded to 2 decimals.
    assert aubrey.projected_points_ppr == 153.34


def test_parses_dst_table_flat():
    out = parse_fantasypros_html(_DST_HTML, "DST")
    # DST has no team trailing the anchor, so team should be None and
    # position should be reported as DEF (canonical Sleeper position).
    tex = out["houston texans"]
    assert tex.position == "DEF"
    assert tex.team is None
    assert tex.stats["def_sack"] == 49.2
    assert tex.stats["def_int"] == 14.1
    assert tex.stats["def_pa"] == 321.2
    assert tex.stats["def_yds_allowed"] == 5067.0  # comma stripped


def test_missing_table_returns_empty_dict():
    out = parse_fantasypros_html("<html><body>no table here</body></html>", "QB")
    assert out == {}


def test_unparseable_headers_returns_empty():
    # Group label "BLOCKING" is unrecognized — bail rather than guess.
    bad = _QB_HTML.replace("PASSING", "BLOCKING")
    out = parse_fantasypros_html(bad, "QB")
    assert out == {}


def test_apostrophe_player_name_normalizes_correctly():
    # Sanity check: the normalized_name should be the cross-source key
    # we expect for an apostrophe name. Use Kaimi Fairbairn from K page.
    html = _K_HTML.replace("Brandon Aubrey", "Ka'imi Fairbairn").replace("DAL", "HOU")
    out = parse_fantasypros_html(html, "K")
    assert "kaimi fairbairn" in out
    assert out["kaimi fairbairn"].name == "Ka'imi Fairbairn"
    assert out["kaimi fairbairn"].team == "HOU"
