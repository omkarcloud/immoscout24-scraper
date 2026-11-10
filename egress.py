"""The one network helper the immoscout24 module needs: the Accept-Language
its sessions send to immobilienscout24.at. ImmoScout24 is a German-language
portal, so every session announces the list a desktop Chrome in Germany
sends — on your own connection or on IMMOSCOUT24_PROXY alike. (Calls to the
German app API send the app's own fixed German headers.)"""

GERMAN = "de-DE,de;q=0.9,en-US;q=0.8,en;q=0.7"


def site_accept_language(site=None):
    return GERMAN


def accept_language(proxy=None, country=None):
    return GERMAN
