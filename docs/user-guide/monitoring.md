# User guide — monitoring

This page covers how to run anomaly-monitoring workflows for monitored entities.

## When to use this page

Use this page when starting, validating, or stopping monitoring workloads from the UI.

## Audience

- Operators managing anomaly-monitoring workloads.

## What monitoring does

- Starts one RADAR workload for the selected numeric readings, always as a monitoring pipeline.
- Runs either a static-baseline or adaptive-stream detection strategy.
- Persists monitoring evidence and detected anomaly records for the web app.

## Create a monitor

**Create** in the Monitoring workspace (`/?create=monitoring`) opens the
pipeline workbench described below. A reading's **Configure monitoring** link
opens it with that reading preselected.

When an operator sets `TACTIC_PIPELINE_AUTHORING_ENABLED=false` (also the
root `docker-compose.yml` fallback when `.env` omits it), Create shows the
form-based setup instead:

1. Select one or more currently unclaimed numeric readings.
2. Choose a monitoring strategy and model.
3. Keep the defaults for a first-run validation; tune parameters only when the baseline is understood.
4. Start monitoring. The form's configuration becomes the equivalent pipeline,
   so the started service is inspected, stopped and replaced like any other.
5. Observe the service stage, monitoring evidence, and resulting anomalies.

Either way, every selected reading must already be collected as a numeric
reading in **Sources**.

## Service health and coverage

Coverage in the service overview reports known discarded observations and possible
interruptions. RADAR currently consumes a best-effort MQTT stream without a
durable replay cursor. Queue overflow, explicit throttling, invalid inputs and
connection interruptions can leave gaps. New traffic does not repair those gaps:
the monitor keeps its coverage warning even after it resumes processing. Removing
and recreating the monitor starts a new calibration and coverage history.

Throttling is disabled by default. Operators can configure a positive aggregate
limit across all of a monitor's subscribed readings; excess observations are then
counted and reported as lost monitoring coverage.

Monitoring activity separates runtime heartbeats from valid input, inference and
evidence persistence. A running detector becomes degraded if a required input is
older than the configured sensor freshness budget, scoring stops, or evidence
waits too long to commit. The service overview names missing or stale inputs and
shows the last successful inference and evidence commit. Activity recovers when
fresh inputs and scoring resume; historical coverage warnings remain visible.

## Strategy summary

| Strategy | Best suited to | Runtime behaviour |
| --- | --- | --- |
| Static baseline | Signals with a representative training/calibration period | Trains and calibrates first, then scores later observations; exposes conformal and martingale evidence |
| Adaptive stream | Signals whose behaviour should be learned continuously | Warms up, scores each observation before learning it, and adapts its preprocessing/detector state |


## Detector and alarm semantics

A static service consumes consecutive, non-overlapping phases: baseline training,
calibration, and online inference. Inference produces one conformal p-value and
feeds the same ordered stream to every configured martingale tracker. Trackers may
use `power`, `simple_mixture`, or `simple_jumper` betting and may alarm on the
all-history martingale, harmonic restarted martingale, CUSUM, or
Shiryaev-Roberts statistic. An anomaly is emitted when any tracker records a new
threshold crossing. The default is power betting with epsilon `0.5`, the
restarted statistic, and threshold `100`.

The setup form is deliberately stricter than the server on two values: it asks
for a reading freshness of at least 1 second and a betting epsilon, minimum
epsilon or jumper redistribution of at least `0.0001`. Smaller values are almost
certainly typos.

Ville thresholds on the all-history and harmonic restarted statistics retain
their anytime-valid interpretation. CUSUM and Shiryaev-Roberts thresholds are
change-detection parameters and must be calibrated for the intended null stream;
`1 / threshold` is not presented as their false-alarm probability.

A design can combine up to four detectors, such as one for each group of
readings. Each detector's score is ranked against its own calibration scores, so
detectors on different scales need no tuning. The calibration step's **Combine
detectors** setting decides how the ranks make one: **Strongest**, the default,
follows the most surprised detector, so a change that one detector sees is
enough; **Average** follows their mean, so a change has to show in several
detectors, or strongly in one. The setting appears once the design has two
detectors, and the calibration card then reads, for example, *Strongest of 2
detectors*. When every detector is fitted once, the combined rank becomes a
p-value that behaves like a single detector's, so the martingale trackers and
their thresholds keep their meaning. With a detector that learns continuously,
the design alarms when the combined rank exceeds the rule's quantile of the
combined ranks it saw during calibration, and it starts calibrating once its
slowest detector is ready.

Every ready-phase inference is persisted in `monitoring_evidence`, including the
p-value or score, sensor set, aggregate alarm flag, and bounded
`tracker_results` evidence for every configured martingale. A design that
combines detectors also records each detector's score and surprise beside the
combined value, and every inference keeps the features its detectors scored.
Charts draw each selected alarm statistic on a logarithmic secondary axis with
its threshold, shaded above it from each evaluation to the next. Evidence more
than four decades above the threshold is marked at the top edge instead of
stretching the axis. The line joins consecutive evaluations and breaks only
across a pause, such as one a Gate holds back. A **Detector inputs** pane under
the readings plots the scored features, so derived values such as phase
deviations sit beside the raw readings. A feature that a forecaster step scores
also shows what the step expected: the forecast as a dashed line, and around it
a band of the values that raise no alarm. A value outside the band is one the
step scored above its boundary. The band is missing while the boundary is still
being learned and when the design combines several detectors, because then no
single step has a boundary of its own. Telemetry and evidence use the same payload
event timestamp and share zoom and crosshair, so observations from one inference
stay vertically aligned; receive time is used only when a publisher omits its
event timestamp.

## Reading ownership

A reading may belong to only one active monitoring service. TACTIC serializes
claims in PostgreSQL and rejects overlapping MQTT filters, including `+` and `#`
wildcard overlap. Topic levels are literal: for example, charger IDs `charger-1`
and `charger-10` do not overlap. Stop or remove the existing service before
assigning its readings elsewhere.

## Visual monitoring pipelines

The setup page is the processing graph under a compact header. The header holds
the service name and two shortcuts: the input summary, such as **Room · 3
readings**, opens the **Input** step, and how the detectors learn, such as
**Learns continuously**, opens **Service settings**. A new service opens at its Input step, where **Readings from** picks
the entity and **Readings to monitor** its readings; a saved template or a
service being replaced opens at its graph. The main actions are **Load
template**, **Save template** and **Start monitoring**. Starting a service never
requires saving a template.

**Load template** offers the built-in static and adaptive starting flows plus
**Your templates**; **Manage templates** opens the shared template library.
Loading never changes the source template, and **Undo** restores the previous
flow. **Save template** stores the current graph and layout under its own
template name, independently of the service name. A concurrent edit keeps your
work and offers to save it as a new template.

Read a graph from left to right. Each card names its step family (Input,
Prepare, Combine, Normalize, Reduce, Route, Transform, Detector, Calibration,
Detection rule or Evidence output), its title and its underlying operation; a
step that learns also says how (**Learns continuously**, **Fitted once** or
**Pretrained**), and a detector that learns nothing says **No training**; renaming a card helps explain its purpose while the operation name
remains visible. Below the title, a card summarizes the settings that differ from
their defaults, such as a scaling range, and a **Select features** card lists the
readings it keeps. Ports carry their data type as a colored dot, and connections
are solid directional links in the same color, without text labels. Once the graph
has been checked, a features output dot shows how many features leave it; hover
over the dot for their names. The canvas has no separate legend; type names appear
on hover, in the inspector and in accessible descriptions. Scores are
model-specific; the calibration step makes them comparable (**Calibrated
scores**).

**Add step** lists every step, grouped by family, with one line on what each
does and, for a step that learns, how it learns. Search by name, description or family; the arrow keys
move through the list, and Enter in the search box adds the first match. Drag a
step onto the canvas, or click it to add it beside the selected step without
changing connections. To put a step into an existing
connection, point at the connection, or select it, and choose **+**. The menu lists
only the steps that fit there; the new step is connected on both sides and takes
the connection's place in a merge's input order. Drawing a connection onto an
input that is already connected replaces its connection: the dot's hover text
names the connection it replaces, the canvas confirms the change and **Undo**
restores it. A step that learns can only feed a detector that learns the same
way; the check names a step that does not. A design has one
input, calibration step, detection rule and output, so the menu does not offer
them again; it links to the existing steps instead. A detector's settings offer
**Add another detector**: it adds a detector with the same model that reads the
same features and connects it to the calibration step, up to four detectors. Change its model or its input afterwards like any step's. **Service settings** and **Step settings** open the side panel.
Step settings provide the same connection editing on keyboards and narrow
screens, listing compatible, cycle-free upstream choices.
**Locate selected component** brings its card into a readable view and **Fit
entire graph** shows the whole graph. **Arrange** lays out the graph while
preserving processing order; the magnet button (**Snap to grid**) toggles grid
snapping. Undo and redo also work with Ctrl/Cmd+Z and Shift+Ctrl/Cmd+Z outside
text fields. Click empty canvas or press Escape to release a selection before
using Delete. An unsaved setup survives a reload of the same browser tab, and
**Reset** discards it.

Every edit is checked shortly after it is made. The status chip beside the
panel buttons shows the result: **Valid** with the time until the first alarm
can come, or the number of issues. Open it to list the issues; selecting one
opens that step. When a check cannot reach the server, the chip shows **Not
checked** and offers **Check again**.

A design has no strategy to choose. Three settings decide how it detects:

- **Detector model**, in a detector's settings, lists the models by how they
  learn: **Learns continuously**, **Fitted once**, **Pretrained** or **No
  training**. Detectors that learn in different ways can run in one design. Choosing a model that
  learns differently moves the learned steps only that detector reads to their
  counterparts, such as **Standard scaling** to **Online standard scaling**,
  and they keep the settings both versions share.
- **Calibration method**, in the calibration step's settings, decides how scores
  become alarms. **Fixed split** ranks every later score against a calibration
  window that then stays as it is. The other methods keep moving a boundary as
  scores arrive, so they follow data that drifts. Each method says what it
  holds: **Exact while data stays alike**, **Long-run alarm rate** (over a long
  run the share of scores above the boundary approaches the **Target alarm
  rate**) or **No guarantee**. That share counts every score above the
  boundary, anomalies included, so it is not a false alarm rate.
- **Detection rule** follows the other two, and the picker marks the rules that
  do not fit the design. A method that adapts alarms by the **Exceedance rule**,
  once **Exceedances in a row** scores are above the boundary; more than one
  ignores short spikes. Under the fixed split, detectors that are all fitted
  once alarm with the **Conformal alarm policy**, and a design with a detector
  that learns continuously, a pretrained one or a rule detector alarms on the
  **Calibrated score threshold**.

The **Rule detector** learns nothing: the value of the one feature it reads is
its score, and a higher value counts as more anomalous. A step before it states
the rule. A **Formula** such as `if(temperature > 80, 1, 0)` is a hard limit,
and one such as `abs(power - voltage * current)` scores how far a reading is
from what it should be. Set the formula's **Result** to **Replace features**,
or add **Select features**, so that one feature arrives. The score then takes
the path of a learned detector's: the calibration step ranks it, the detection
rule alarms on it, and the alarm is recorded and reviewed like any other. Under
the **Fixed split**, a flag that stays 0 through calibration alarms whenever it
is 1. A rule detector reads only steps that do not learn, runs beside other
detectors, and does not run under the **Conformal alarm policy**. A design
whose detectors are all rule detectors has no learning window: calibration
starts with its first observation, and **Service settings** ask only for
**Calibration observations**. The form-based setup has no step to state a rule
in, so it does not offer the Rule detector.

A pretrained forecaster, such as the **Timestral forecaster**, does not carry
its model: the weights live in the deployment's forecast service. The step's
settings list every checkpoint under **Model weights** with its size and state:
**Ready**, **Not downloaded**, **Downloading** with its progress, or **Download
failed** with the reason. **Download** fetches a checkpoint before a monitor
needs it, and **Try again** repeats a failed download; both need the permission
to manage monitors. A monitor that starts before its checkpoint is ready scores
nothing until the download ends, and its coverage shows the values it lost.
Where the deployment has no forecast service, the step is greyed out in **Add
step** with that reason and cannot be chosen as a detector model.

When a change also moves steps or the detection rule, a notice says what
changed, and **Undo** reverses all of it.
In **Service settings**, **Before the first alarm** shows the observations Prepare steps need first, then
the learning and calibration phases. Once every chosen reading reports how often it arrives, it also
shows durations. The slowest reading paces observations, because each
observation waits for all of its readings.

To keep features raw, branch from **Aligned inputs** and select the required
features. **Pass through** preserves the values at its input. **Merge features**
combines columns from the same aligned observation in the explicit input order;
rename colliding feature names before combining branches. A card title changes
presentation only; the **Rename features** component changes execution.

Scaling and projection steps use every feature that reaches them until **Applies
to** narrows them; unchecked features pass through unchanged and keep their place.
**Result** decides where the output goes. A scaler replaces the values it uses, or
with **Add new features** keeps them and adds copies named with a suffix, such as
`dc_voltage_std`. A projection replaces the features it uses with its components,
or with **Keep features** keeps every feature and adds the components. Added
features follow the untouched ones, in the order of **Applies to**. The card lists
the features a step uses, or the ones it adds. A chosen feature that no longer
arrives stays listed as *not available here* until it is unchecked, and a suffix
that repeats an existing name is refused; both stop **Start monitoring**. One
scoped step computes the same values as a branch of **Select features**, the step
and **Merge features**.

**Prepare** steps clean and derive features before anything learns. They run once
per observation, in arrival order, and compute the same values however the
detectors learn; a detector fitted once keeps them running while it trains, so
their windows never restart.

- **Smooth** averages recent values: exponentially, over a rolling window, or
  by a **Time constant** in seconds. A time constant weighs values by the time
  since they were measured, so readings every second and every ten seconds are
  smoothed alike: a lasting change shows to 63% after one time constant and to
  95% after three, however many observations arrive meanwhile.
- **Despike** replaces a value further than **Threshold** robust deviations from
  the median of its window with that median. The detector then sees the median in
  place of the spike; the evidence keeps the raw reading.
- **Change** adds the difference or percent change since **Lag** observations
  back, or the value from then.
- **Rolling statistic** adds the mean, median, minimum, maximum, standard
  deviation, range, sum, quantile, interquartile range (IQR), median absolute
  deviation (MAD), or fitted slope of the last **Window** values. Quantiles use
  linear interpolation; MAD is unscaled. Slope measures change per observation,
  not per second. Six more statistics place the latest value in its window or
  describe the window's shape:
  - **zscore** is the latest value's distance from the window's mean in
    standard deviations, and **robust_zscore** its distance from the median in
    scaled MADs, which a few outliers in the window do not stretch. Where more
    than half of the window holds one value, the mean absolute deviation
    stands in for the MAD.
  - **rank** runs from 0, the lowest value of the window, to 1, the highest;
    equal values count half.
  - **rms** is the root mean square, the usual size of a signal that swings
    around 0.
  - **skewness** is positive when the window has a tail of high values, and
    **kurtosis** is positive when it has heavier tails than a normal
    distribution.

  A window that holds one value throughout has no spread: its scores, skewness
  and kurtosis are 0 and its rank is 0.5.
- **Accumulate** adds a running total, minimum, maximum or count. It starts
  with the first observation reaching the step, continues across checkpoint
  recovery, and starts over in a new run. A total of a 0/1 feature counts its
  true values, and **count** numbers the observations themselves from 1.
  **Reset when** takes a condition over the features that arrive, such as
  `dc_current < 1`: each observation where it holds starts over and is the
  first of the new accumulation, so a count reads 1 there. With it, a total
  becomes the energy of one charging session and a count the observations
  since the last door opening. Without a reset a total keeps growing, so a
  detector that learned its early values soon sees only values it never met.
  Before such a total reaches a detector, take its **Change** or a **Rolling
  statistic**, or compare it in a Condition.
- **Hold** keeps each value from the last observation where **Update when**
  held, such as `valid == 1` to carry the last valid measurement through the
  observations in between. The first observation is always taken, so the step
  has a value from the start.
- **Rolling relation** compares each feature with the one chosen under
  **Against** over the last **Window** observations, at least 3: their
  **correlation** from -1 to 1, their **covariance**, the **slope** of the
  feature per unit of the other one, or the **residual**, how far the latest
  value lies from the line fitted through the window. The correlation of a
  current with the power it should drive stays near 1 until something comes
  loose. **Applies to** starts with every other feature. A window where either
  feature keeps one value has no direction: correlation, covariance and slope
  are 0, and the residual is the latest value's distance from the window's
  mean.
- **Math** takes a logarithm, square root, absolute value or square, or computes
  scale × x + offset.
- **Range check** clips values to **Low** and **High**, or skips observations
  outside them.
- **Time features** adds features of the time each observation was measured
  at, whichever are switched on:
  - **Seconds since the previous observation** adds `dt`. With it a formula
    turns a difference into a rate, `dc_current_diff1 / dt`, and a power into
    energy, `power * dt` under **Accumulate**. `dt` is always above 0, so
    dividing by it skips nothing. The first observation has none before it,
    so the step is ready after two.
  - **Hour of day** adds `hour`, from 0 at midnight up to 24 with minutes as a
    fraction, and **Day of week** adds `weekday`, 1 for Monday to 7 for Sunday.
  - **Daily cycle** adds `hour_sin` and `hour_cos`, and **Weekly cycle**
    `weekday_sin` and `weekday_cos`. They place the time on a circle, where
    23:59 lies next to 0:00 and Sunday night next to Monday morning, so a
    detector sees them as neighbours.

  The hour and the weekday follow **Time zone**, such as `Europe/Berlin`, with
  its daylight saving time, so a pattern that follows working hours stays in
  place all year. Left empty it is UTC. The step has no **Applies to**: it
  keeps the features that arrive and adds its own, and a name that already
  arrives has to be renamed first.

Prepare steps use **Applies to**, **Result** and **Suffix** like scaling steps.
**Change**, **Rolling statistic**, **Accumulate**, **Hold** and **Rolling
relation** add features by default, such as `dc_voltage_diff1`,
`dc_voltage_mean60`, `dc_voltage_total`, `dc_voltage_held` and
`dc_voltage_corr60`; the others replace values. A count is named
`dc_voltage_count`, and a covariance, slope or residual over 60 observations
ends in `cov60`, `beta60` or `resid60`. A **Smooth** by a time constant of 60
seconds adds `dc_voltage_smooth60s`.
A rolling quantile is named after its quantile as a percentage, so the 0.1 and
0.9 quantiles of 60 values sit side by side as `dc_voltage_q10_60` and
`dc_voltage_q90_60`. A step
with a window has its first value once the window is full, and steps in a chain
add up: **Smooth** over 10 followed by **Change** over 1 has its first value at
the 11th observation, and its settings say **Ready after 11 observations**.
**Before the first alarm** counts those observations as
**Preparing**; meanwhile the service shows how many observations are prepared,
and nothing learns. A window holds at most 3,600 values per feature,
and a design's Prepare windows hold at most 50,000 values in all. A **Rolling
relation** keeps two windows per feature, its own and one of the feature it is
compared with.

**Time features** and **Smooth** by time constant read the observation's time,
as [Observation time and alignment](#observation-time-and-alignment) defines
it, never the moment it happened to be processed, so a Dojo replay of recorded
data computes the same values as the live monitor did. The time between two
observations counts from the previous observation the step used: one that was
skipped, or that a **Gate** before the step held back, is not counted, so the
next `dt` spans it.

An observation a Prepare step cannot use is skipped as a whole: a logarithm or
root outside its domain, a percent change from zero, a result too large to
represent, a value outside a skipping **Range check**, or an observation that
is not later than the previous one at a step that reads time. Skipping changes no
step's state, nothing learns from the observation, and it counts as a coverage
gap. The step's diagnostics count skipped observations by reason. Evidence
always records the raw readings. Learned steps and the detector skip an
observation the same way when it fails them without changing what they learned,
such as a value the detector cannot score. Only a failure that can leave learned
state uncertain, such as the detector failing while it learns, stops the service.

**Combine** steps compute one feature from several, usually after the features
were prepared one by one. They run in the Prepare stage as well and have their
value from the first observation.

- **Aggregate** computes the mean, sum, minimum, maximum, standard deviation or
  range across the features in **Applies to**, at least two of them.
- **Formula** computes a feature from the features that arrive, such as
  `dc_voltage * dc_current`. It knows `+ - * / ^`, parentheses, and `abs`,
  `sqrt`, `log`, `log1p`, `exp`, `min`, `max` and `clip(value, low, high)`. A name
  with other characters goes between backticks, such as `` `dc-voltage` ``; the
  buttons below the formula insert the features that arrive.

`if(condition, when_true, when_false)` chooses a numeric value. Only the selected
branch is evaluated, so `if(dc_current != 0, power / dc_current, 0)` can handle
zero current without skipping the observation. Conditions use comparisons and
`and`, `or`, `not`; conditional formulas can be nested. Guard a division, a
logarithm or a square root on the feature itself, as above: the check follows a
comparison of the feature with a number, not a flag computed from it, so
`if(running == 1, power / dc_current, 0)` still warns that a current of 0 is
skipped.

More functions round, wrap and combine values:

| Function | Result |
| --- | --- |
| `round(x)`, `floor(x)`, `ceil(x)` | The nearest, next lower or next higher whole number. A half rounds away from 0, so `round(2.5)` is 3. For two decimals, write `round(x * 100) / 100`. |
| `sign(x)` | -1, 0 or 1. |
| `mod(x, divisor)` | The remainder, with the divisor's sign: `mod(hour - 1, 24)` is 23 at hour 0. A divisor of 0 skips the observation. |
| `mean(a, b, …)`, `sum(a, b, …)` | The mean or the sum of two or more values. |
| `hypot(a, b, …)` | The length of a vector, `sqrt(a^2 + b^2 + …)`. |
| `sin(x)`, `cos(x)`, `atan2(y, x)` | Angles in radians. `pi()` is π, so `sin(2 * pi() * hour / 24)` turns an hour of the day into a smooth daily cycle. |

Both keep the features they use and add the result, named by **Name**, or
`formula` and the function's name, such as `mean`, when it is empty. A second
Formula or Aggregate that would compute a name an earlier one already uses
starts with its own, such as `formula_2` or `mean_2`. **Replace
features** removes the features they use instead.

Three more Combine steps provide small building blocks for later calculations:

- **Constant** adds a named value to every observation, such as `limit = 80`.
  Downstream formulas and conditions can reuse that feature. A detector learns
  nothing from a value that never changes, so the check warns when one reaches
  a detector or a scaling step; leave it out with **Select features** once the
  formulas have used it.
- **Condition** adds a numeric flag: 1 when its condition holds, 0 otherwise.
  It keeps every observation. For example, `temperature > limit` can feed a
  three-observation rolling sum, then another Condition checking whether that
  sum is at least two. Use `flag == 1` to combine flags in further conditions.
- **Set feature** computes a named feature, replacing it in its existing position
  if present or adding it if new. Other features remain unchanged. For example,
  set `current` to `if(running == 1, current, 0)` while preserving voltage and
  temperature. Unlike Formula's **Replace features**, it replaces only the named
  feature, even when the expression reads several inputs.

Constant and Condition require a free output name. Set feature explicitly allows
replacement, and a name it adds uses letters, digits and underscores like any
computed name. A Set feature that reads the feature it replaces continues it:
**Features** keeps the reading and the earlier steps on its trail. The check
warns about a Condition that is always or never true, and about a Set feature
that reads no feature. These steps run before learned scaling and projection,
like Formula.

**Calculate** computes several named features in one step, one per line:

```text
# Electrical power and how much of the limit it uses
power = dc_voltage * dc_current
share = power / 11000
dc_current = if(dc_current < 0.05, 0, dc_current)
```

Each line is `name = formula`, and a line reads the features that arrive and
the names written above it, so `share` can use `power`. A name that already
arrives is replaced in its place, like **Set feature**; a new name is added
after the others. Lines that start with `#` are notes, and a step holds up to
32 formulas. A problem names its line, such as *Line 3: Unknown feature powr
at character 9*, and **Use** fixes it in that line. Suggestions list the names
written above the line being typed. The check warns per line about values that
will be skipped, like it does for a Formula.

**For each feature** runs one Formula once per feature chosen under **For
each**, with `x` standing for that feature, so `x / i_mean - 1` on `L1`, `L2`
and `L3` computes three relative deviations in one step. Every result is
computed from the observation as it arrives. **Add new features** keeps the
features and adds `<feature>_<suffix>`, such as `L1_dev`, named by **Suffix**,
or `L1_formula` when it is empty; **Replace values** puts each result in place
of its feature. `x` means nothing in a Formula that computes one feature, and a
formula for each feature that never reads `x` gives every feature the same
value, which the check warns about. [Monitor three phases together](phase-monitoring.md)
walks through it. A formula that cannot be read
says where, such as *The expression ends too early at character 12*, and an
unknown feature or function suggests the closest one, which **Use** puts in its
place. While you type, suggestions list the features that arrive and the
functions, and in a condition `and`, `or` and `not`: the arrow keys choose, Enter
or Tab inserts, and Escape closes the list. **Range** below a formula shows the
values its result can take. When an earlier step
limits a feature's range, such as a **Range check**, the check knows the range of
the result too and warns about values that will be skipped, such as a division by
a feature that can be 0 or the logarithm of one that can be negative. When every
observation would be skipped, it is an error.

A **Gate** lets only the observations where its **Condition** holds go on, such
as `dc_current > 1` to monitor a charger only while it charges. Compare with
`<`, `<=`, `>`, `>=`, `==` and `!=`, and join comparisons with `and`, `or` and
`not`. The observations it holds back are recorded, but nothing learns from them
or scores them, and they are not coverage gaps. Steps before the Gate still see
them; steps after it do not, so their windows fill only with observations that
pass. The Prepare summary counts held-back observations, and the Gate's
diagnostics read **Held back** while its condition does not hold. A condition
that is never true is an error, and one that is always true a warning. **Before
the first alarm** and **Ready after** then say *at least*, because the
observations a Gate holds back do not count.

A **Mute alarms** step raises no alarm while its condition holds, such as
`speed < 100` while a machine runs up. Unlike a Gate it lets every observation
through: the steps after it, the detectors and the calibration learn and score
as usual, so the charts keep their line and the detector keeps following the
process. Only the alarm is held back. An alarm that would have been raised is
kept as **muted**: the monitor's chart shows it as an open dot where a raised
alarm is a filled one, hover reads **Alarm: muted**, and no alarm is listed for
it. When the condition stops holding and the alarm still stands, it is raised
then. The Prepare summary counts the observations scored with alarms muted, and
the step's diagnostics say when its condition holds. A condition that is always
true is an error, because no alarm would ever be raised, and one that is never
true a warning. In a Dojo run a muted observation counts as no alarm. Choose a
Gate when the detector should not learn from the readings at all, such as a
standstill, and Mute alarms when it should and only the alarms would be noise.

A step that chooses features, such as **Select features** or **Applies to**,
lists the features that arrive once the check has worked them out. When an
earlier step has an error, the check cannot, and the step names the earlier one
and its problem instead, with **Go to** to open it.

**Features** beside **Graph** lists the features the detector receives, one row
each: the reading it comes from, the steps that change it on the way, and the
name the detector sees. Features made from several, such as a formula's result,
follow the readings, and the Gates and Mute alarms steps sit above the rows
because they decide for every feature at once. **Raw** means no step changes the feature, and
selecting a step opens its settings. **+** in a row adds a step for that feature
alone: a Prepare or Combine step goes in before anything learns, and a learned
step just before the detector. A feature that a learned step makes, such as a
projection's component, takes no Prepare step, and the menu says why. The view
follows the latest check, so it waits while an edit is checked. With several
detectors, a switch above the rows chooses whose features it lists, starting
with the selected detector. A Prepare step runs before anything learns, so when
its place is on a path several detectors share, the row's menu names the other
detectors it also changes.

**Robust scaling** centers each feature on its median and divides by its
interquartile range, so occasional spikes shift it less than standard scaling.
The static step learns them from the training window. **Online robust scaling**
uses a window of recent observations per feature, 256 by default, and is ready
after **Min Samples** observations.

Unchecking readings in **Readings to monitor** changes the input slots and
bindings together; a service accepts up to 100 readings. Each reading's feature
is named after its label, such as `dc_voltage` for *DC Voltage*; a repeated label
continues with `_2`, `_3` and so on. Saved templates keep their own input names.
**Start monitoring** opens the Input step when a reading is still missing. Every slot binds a
distinct numeric reading on one entity. Labels are cosmetic; expected units
require an exact match, and unknown units remain unknown.

**Start monitoring** validates the graph and starts the service through the same
preflight, reading claims, capacity checks and worker heartbeat as every other
start. Progress stays visible across navigation and reload: **Recover start
request** resumes an uncertain request, **Cancel start** stops it, and a failed
start offers **Return to setup**. A rejected request keeps the setup editable.

A running service always displays its bound, immutable execution. Its
arrangement can be saved independently. The live inspector shows one coherent
sampled observation, separates score and post-learning passes, and marks nodes
that did not execute. Snapshot age is visible; fresh diagnostics do not imply
persisted evidence is current. Static training appears as a batch summary.
**Run timeline**, under a pipeline service, lists what its run went through,
newest first: each setup step, when the worker started or resumed from saved
state, each stage with the time spent in the previous one, the alarm threshold and
training sizes once learning ends, coverage losses, crashes the cluster recorded
(an out-of-memory kill is named as such) and how the run ended. A failed run opens
it with the final error. The timeline and the run's last status stay after the
service is removed. Runs started before this release have none.

Configuration issues and sampled runtime state have separate badges. When the
policy combines detectors, selecting it lists each detector's score and surprise
for the sampled observation, and a selected detector shows its surprise beside
its score. A chart's tooltip lists the same for each evidence row.

**Edit service** opens the running definition, layout and bindings. **Apply
changes** explains the interruption and fresh learning, then replaces the
service through the same preflight and handoff. Both sets of readings stay
reserved during preflight and handoff, and a failed preflight leaves the
predecessor running. After retirement, cancellation or failure does not silently
revive it. History remains inspectable after a service is removed. Older library,
revision and in-flight activation links still open.

Static preprocessing fits only the training window and stays frozen. Adaptive
preprocessing initializes before downstream learning; its warm-up counter counts
successful detector updates. PCA has separate centered batch and uncentered
incremental implementations. Changing online preprocessing does not transform
historical geometry already retained by the detector.

## Adaptive model selection

Adaptive monitoring uses the Aberrant release pinned by RADAR. Models are grouped by the library's
algorithm family and filtered by the number of features after preprocessing.
The original 24 numeric detectors remain available; scalar and multivariate
rolling matrix profiles add detection of unusual sequences across one or multiple
channels. Graph-event detectors and score-policy wrappers are excluded.

Warm-up and calibration are separate. The requested warm-up must satisfy the
selected model's minimum history and PCA initialization, when enabled. RADAR
validates these requirements before consuming telemetry. Calibration continues
to score before learning, freezes the higher empirical quantile, and monitoring
learns every valid observation, including anomalies.

Half-Space Trees requires features in `[0, 1]`. Selecting it chooses min-max
scaling to this range and removes projections. Values beyond previously seen
extremes are clipped before scoring. Without scaling, values outside `[0, 1]`
are rejected. The UI warns when a model has growing memory requirements.

Matrix-profile subsequences count aligned observations, not elapsed seconds.
Use consistently sampled telemetry: the sensor barrier synchronizes incoming
updates but does not resample them onto a uniform clock. Normalized profiles
compare shape independently of per-channel level and amplitude; disable
normalization when those changes should contribute to the score, taking care
that channels with larger units can dominate raw distances.

KNN exposes its FAISS window and warm-up as nested similarity-engine settings.
Existing saved model IDs and the legacy flat KNN parameters are translated on
input. Legacy histogram `max_bins` becomes `max_depth`; conflicting old and new
parameter values are rejected.

## Stop and cleanup workflow

1. Open **Monitoring** at `/` and select the service.
2. Choose **Stop and remove service** (or **Remove service** once it has stopped).
3. Confirm that the service is absent from the service list and that its readings are available again.

With the default `ephemeral` lifecycle, TACTIC also cleans up managed workloads when it restarts.

## Operational checks

```bash
curl --fail http://localhost:8000/v1/monitors
curl --fail http://localhost:8000/v1/detectors
curl --fail "http://localhost:8000/v1/evidence?reading_id=<reading-id>"
curl --fail http://localhost:8000/v1/alarms/count
```

## Failure modes

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Start fails with a validation error | Invalid model parameters or sensors already claimed | Retry with defaults and check active services |
| Service runs but evidence is empty | No MQTT data flow or warm-up/calibration is incomplete | Verify the topic stream and allow the initial window to complete |
| Service disappears after a restart | Ephemeral lifecycle is configured | Use `TACTIC_RADAR_WORKLOAD_LIFECYCLE=persistent` only when persistence is required |
| Model endpoint fails | TACTIC is unreachable | Check TACTIC `/ready` and its logs |
| A pipeline service failed or keeps restarting | A node failed, the worker ran out of memory, or the database refused its writes | Open **Run timeline**; in production, search Grafana for its `service_id` (see [Production](../operations/production.md#logs-and-grafana)) |
| Evidence exists but no anomalies appear | Current observations have not crossed the detector threshold | Inspect evidence before changing model parameters |

## Telemetry persistence during outages

The MQTT proxy uses one database worker and a bounded pending batch. Database
failures retain the active batch for retry and apply backpressure to ingestion.
Shutdown attempts to drain the buffers within the configured deadline and logs
unwritten records if it cannot. These buffers are in memory, not a durable spool;
forced termination does not guarantee delivery.

## Observation time and alignment

RADAR uses a payload's `timestamp` as observation time, falling back to MQTT
receipt time when it is absent. It rejects nonfinite times, observations older
than 30 seconds, times more than 5 seconds ahead of the worker, and duplicate or
regressing timestamps for the same reading. Rejected inputs are counted as
coverage gaps and cannot refresh valid-input activity or advance the detector.
Without a source timestamp or event identity, distinct deliveries cannot be
deduplicated reliably.

Pipeline steps that read time, **Time features** and **Smooth** by time
constant, use the latest observation time among the readings of the aligned
vector.

An aligned vector also requires fresh receipts and observation times within
5 seconds of one another. Newer compatible readings unblock alignment; a blocked
frame never advances the model. Set `performance_config.observation_max_age_seconds`,
`observation_future_tolerance_seconds`, and `alignment_max_skew_seconds` in the
monitor API configuration to match measured source delays and sampling periods.
Standalone workers expose the corresponding `RADAR_*` environment settings.
Keep source and worker clocks synchronized. These settings form part of the
checkpoint compatibility signature; a changed alignment contract requires a new
monitor baseline.

## Related pages

- [Backend API](../reference/backend-api.md)
- [Architecture](../development/architecture.md)
- [Environment variables](../reference/environment-variables.md)
- [Testing and debugging](../development/testing-debugging.md)
- [RADAR recovery](../operations/radar-recovery.md)
- [RADAR deployment capacity](../operations/radar-capacity.md)
