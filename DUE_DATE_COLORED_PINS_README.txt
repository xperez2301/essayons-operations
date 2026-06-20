EOMS v1.3.9 Due Date Colored Pins + Compact Available Stores

Adds:
- Map pin click auto-selects the matching Available Store card.
- Selected card scrolls into view and highlights.
- Numbered custom map pins.
- Due-date color logic:
  Green = more than 4 days before due date or no due date captured
  Amber = due within 4 days
  Red = past due
- Available Stores panel is smaller and more compact.
- Queue and Dispatch Map show due date where captured.

Important:
Due date capture depends on the printable RMS page exposing Due Date text. If the list page has due date but printable does not, the next build should capture due date from the RMS Queue table during Refresh RMS Queue.
