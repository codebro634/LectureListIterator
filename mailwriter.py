MAIL_TEMPLATE = """
Sehr geehrte{SUFFIX_GEEHRT} {TITLE} {NAME},

ich organisiere zusammen mit der MaPhy und Informatik Fachschaft den
jährlichen Integrierwettbewerb. Hätten Sie Lust uns zu
unterstützen indem Sie unser Plakat (siehe Anhang) auf Stud.IP in {VERANSTALTUNGEN_PRE} {VERANSTALTUNGEN} zu posten oder als Datei hochzuladen? Das würde uns
riesig helfen! Der Wettbewerb geht in die 5. Runde und wenn Sie
einmal etwas dazu lesen möchten, dann gerne unsere Seite
"integrierwettbewerb.de" klicken 😊

Liebe Grüße,
Robin Schmöcker
"""

def mail_text(lectures, name, gender, title):
    return MAIL_TEMPLATE.format(SUFFIX_GEEHRT = "r" if gender == "m" else "",
                                TITLE = title if title.strip() != "" else ("Herr" if gender == "m" else "Frau"),
                                NAME = name,
                                VERANSTALTUNGEN_PRE = "ihren Veranstaltungen" if len(lectures) > 1 else "ihrer Veranstaltung",
                                VERANSTALTUNGEN =  (", ".join(lectures[:-1]) + f" und {lectures[-1]}") if len(lectures) > 1 else lectures[0])