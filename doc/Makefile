# Makefile pre dokumentáciu IPP 2025/2026 - Interpret SOL26
# Generuje doc.pdf zo zdrojového doc.tex a UML diagramu uml.dot

TEX      := pdflatex
TEXFLAGS := -interaction=nonstopmode -halt-on-error
DOT      := dot

DOC      := doc
UML      := uml

.PHONY: all clean distclean view

all: $(DOC).pdf

# UML diagram: .dot -> .pdf (graphviz)
$(UML).pdf: $(UML).dot
	$(DOT) -Tpdf $< -o $@

# Dokumentácia: .tex + uml.pdf -> .pdf (dva behy pre krížové odkazy)
$(DOC).pdf: $(DOC).tex $(UML).pdf
	$(TEX) $(TEXFLAGS) $(DOC).tex
	$(TEX) $(TEXFLAGS) $(DOC).tex

view: $(DOC).pdf
	xdg-open $(DOC).pdf >/dev/null 2>&1 &

# Upratanie pomocných súborov (log, aux, out, toc), PDF ponecháme
clean:
	rm -f $(DOC).aux $(DOC).log $(DOC).out $(DOC).toc

# Úplné upratanie vrátane výstupných PDF
distclean: clean
	rm -f $(DOC).pdf $(UML).pdf
