--[[
  scale-codeblocks.lua — shrink over-wide code blocks to the text width.

  The TUI scene captures (the `**On screen:**` blocks) are verbatim
  terminal grabs up to ~197 display columns wide.  An A4 page at 1in
  margins fits only ~86 columns of DejaVu Sans Mono at the default size,
  so wide captures run off the right margin and clip.  Line-wrapping
  would shred the box-drawing alignment, so instead we scale each
  over-wide block down uniformly (aspect-ratio preserved, ASCII-art
  intact) until it fits the text block.

  Mechanism: wrap the block in `adjustbox` with `max width=\textwidth`
  around a `BVerbatim` (fancyvrb's box-producing verbatim, which has a
  definite natural width that adjustbox can measure + scale).  `max
  width` only scales DOWN — blocks already within the text width are
  left at natural size, so narrow / syntax-highlighted code (e.g. the
  hand-written bash snippets) is untouched and keeps its styling.

  Only applies to the LaTeX/PDF writer; other output formats pass
  through unchanged.  Requires \usepackage{adjustbox} + \usepackage
  {fancyvrb} in the preamble (added by pdf_builder's header-includes).
]]

-- Wrap only blocks wider than the page can show at full size.  86 cols
-- is the ~1in-margin A4 capacity at 11pt; 85 leaves a hair of safety.
local WIDTH_THRESHOLD = 85

local function max_line_width(text)
  local widest = 0
  for line in (text .. "\n"):gmatch("(.-)\n") do
    local w = utf8.len(line) or #line
    if w > widest then widest = w end
  end
  return widest
end

function CodeBlock(el)
  if not FORMAT:match("latex") then
    return nil
  end
  if max_line_width(el.text) <= WIDTH_THRESHOLD then
    return nil  -- fits already — leave it (and its highlighting) alone
  end
  local latex = table.concat({
    "\\begin{adjustbox}{max width=\\textwidth}",
    "\\begin{BVerbatim}",
    el.text,
    "\\end{BVerbatim}",
    "\\end{adjustbox}",
  }, "\n")
  return pandoc.RawBlock("latex", latex)
end
