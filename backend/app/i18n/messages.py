"""
Vernacular message catalogue for the WhatsApp qualification flow.

Adding a language is a data change: add a key to MESSAGES with the same
message keys. Any key missing from a language falls back to English rather
than crashing, so a partial translation ships safely.

Numbers are formatted with the Indian digit grouping (lakh/crore) because
"Rs 1,25,000" reads as money to the buyer and "Rs 125,000" does not.
"""

from __future__ import annotations

LANGUAGES = {
    "en": "English",
    "hi": "हिन्दी",
    "mr": "मराठी",
    "gu": "ગુજરાતી",
    "ta": "தமிழ்",
}

DEFAULT_LANGUAGE = "en"


def format_inr(amount: float) -> str:
    """Indian digit grouping: 1234567 -> 12,34,567."""
    try:
        amount = int(round(float(amount)))
    except (TypeError, ValueError):
        return str(amount)

    sign = "-" if amount < 0 else ""
    digits = str(abs(amount))

    if len(digits) <= 3:
        return sign + digits

    last3 = digits[-3:]
    rest = digits[:-3]
    parts = []
    while len(rest) > 2:
        parts.insert(0, rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.insert(0, rest)
    return sign + ",".join(parts + [last3])


MESSAGES: dict[str, dict[str, str]] = {
    "en": {
        "ask_language": (
            "Namaste! I am RAAH, your rooftop solar assistant.\n"
            "Please choose your language:\n"
            "1. English\n2. हिन्दी\n3. मराठी\n4. ગુજરાતી\n5. தமிழ்"
        ),
        "ask_segment": (
            "Is this for your *home* or for a *business/factory*?\n"
            "1. Home\n2. Business / Factory / Shop"
        ),
        "ask_ownership": (
            "Do you *own* this roof, or is the property rented?\n"
            "1. I own it\n2. It is rented"
        ),
        "disqualify_rented": (
            "Thank you. A rooftop solar system needs the roof owner's consent, "
            "so we cannot proceed on a rented property right now.\n\n"
            "If you can get written consent from the owner, reply *OWNER OK* "
            "and we will continue. Otherwise we will not trouble you further."
        ),
        "ask_pincode": "Please share your 6-digit *PIN code*.",
        "invalid_pincode": "That does not look like a 6-digit PIN code. Please try again.",
        "ask_roof_area": (
            "Roughly how much *open, shadow-free roof area* do you have, in square feet?\n"
            "A rough number is fine. Reply *DONT KNOW* if you are unsure."
        ),
        "ask_sanctioned_load": (
            "What is the *sanctioned load* on your electricity connection, in kW?\n"
            "You will find it printed on your bill. Reply *DONT KNOW* if unsure."
        ),
        "ask_bills": (
            "Please share your *last 3 monthly electricity bill amounts* in rupees.\n"
            "Example: 1850 2100 1950"
        ),
        "invalid_bills": (
            "I could not read those amounts. Please send 3 numbers separated by spaces.\n"
            "Example: 1850 2100 1950"
        ),
        "ask_gst": (
            "Is your business *GST registered*?\n1. Yes\n2. No"
        ),
        "ask_vintage": "How many *years* has the business been operating?",
        "ask_photo": (
            "Last step: please send a *photo of your roof*, taken from one corner "
            "so most of the roof is visible.\n"
            "This lets us check shadows without sending an engineer to your site."
        ),
        "photo_received": "Photo received. Calculating your solar estimate now...",
        "photo_skipped": "No problem. Calculating with satellite data only...",
        "computing": "Please wait a moment while I run the numbers...",
        "offer_residential": (
            "*Your solar estimate*\n\n"
            "Recommended system: *{capacity} kW*\n"
            "Estimated cost: Rs {gross_capex}\n"
            "PM Surya Ghar subsidy: *- Rs {subsidy}*\n"
            "Your cost after subsidy: Rs {net_capex}\n\n"
            "If you take a loan:\n"
            "Monthly EMI: Rs {emi}\n"
            "Monthly bill savings: Rs {savings}\n"
            "*Net benefit every month: Rs {net_benefit}*\n\n"
            "Payback: about *{payback} years*. After the loan ends, the savings "
            "are entirely yours for 20+ years."
        ),
        "offer_sme": (
            "*Your solar estimate*\n\n"
            "Recommended system: *{capacity} kW*\n"
            "Annual generation: {generation} units\n\n"
            "*Option A - You buy it (CAPEX)*\n"
            "Investment: Rs {gross_capex}\n"
            "Monthly EMI: Rs {emi}\n"
            "Monthly savings: Rs {savings}\n"
            "Net monthly benefit: *Rs {net_benefit}*\n"
            "Year-1 tax saving from accelerated depreciation: Rs {tax_shield}\n"
            "IRR: {irr}% | Payback: {payback} years\n\n"
            "*Option B - Developer owns it (OPEX / PPA)*\n"
            "Your investment: *Rs 0*\n"
            "You pay only Rs {ppa_tariff}/unit instead of Rs {grid_tariff}/unit\n"
            "Net monthly benefit: *Rs {opex_benefit}*\n\n"
            "Our recommendation: *{recommendation}*\n{rationale}"
        ),
        "ask_consent": (
            "Shall I connect you with our nearest certified installer for a free "
            "site visit and a firm quote?\n1. Yes, please\n2. Not right now"
        ),
        "routed": (
            "Done. *{partner}* will contact you within {sla_hours} hours.\n"
            "Your reference number is *{lead_id}*.\n\n"
            "If nobody contacts you in that time, reply *NO CONTACT* and we will "
            "escalate it immediately."
        ),
        "no_partner": (
            "You are qualified, but we do not yet have a certified installer in "
            "PIN code {pincode}. We have added you to the waiting list and will "
            "reach out as soon as a partner is onboarded. Reference: *{lead_id}*"
        ),
        "declined": (
            "Understood. Your estimate is saved under reference *{lead_id}*.\n"
            "Reply *RESUME* any time and we will pick up from here."
        ),
        "dropped_unviable": (
            "Thank you for your time. Based on what you have shared, a rooftop "
            "solar system would not pay for itself at your site right now.\n\n"
            "Main reason: {reason}\n\n"
            "We would rather tell you this now than send someone to sell you "
            "something that does not work. If your electricity usage grows, "
            "reply *CHECK AGAIN*."
        ),
        "fallback": (
            "Sorry, I did not understand that. {retry}\n\n"
            "Reply *RESTART* to begin again or *HELP* to speak to a person."
        ),
        "restart": "Starting over.",
        "help": (
            "A team member will call you shortly. You can also reach us on "
            "the number in our profile."
        ),
        "resume": "Welcome back. Let us continue from where we stopped.",
        "session_expired": (
            "It has been a while, so I will start fresh to make sure the numbers "
            "are current."
        ),
        "escalated": (
            "Thank you for flagging it. We have escalated reference *{lead_id}* "
            "to our partner manager. Someone will call you within "
            "{sla_hours} hours."
        ),
        "dont_know_ack": "No problem, I will estimate that from satellite data.",
    },

    "hi": {
        "ask_language": (
            "नमस्ते! मैं RAAH हूँ, आपका सोलर सहायक।\n"
            "कृपया अपनी भाषा चुनें:\n"
            "1. English\n2. हिन्दी\n3. मराठी\n4. ગુજરાતી\n5. தமிழ்"
        ),
        "ask_segment": (
            "यह आपके *घर* के लिए है या *व्यापार/फैक्ट्री* के लिए?\n"
            "1. घर\n2. व्यापार / फैक्ट्री / दुकान"
        ),
        "ask_ownership": (
            "क्या यह छत *आपकी अपनी* है या किराये की संपत्ति है?\n"
            "1. अपनी है\n2. किराये की है"
        ),
        "disqualify_rented": (
            "धन्यवाद। सोलर सिस्टम लगाने के लिए छत के मालिक की अनुमति ज़रूरी है, "
            "इसलिए किराये की संपत्ति पर हम अभी आगे नहीं बढ़ सकते।\n\n"
            "अगर आप मालिक से लिखित अनुमति ले सकते हैं, तो *OWNER OK* लिखकर भेजें।"
        ),
        "ask_pincode": "कृपया अपना 6 अंकों का *पिन कोड* भेजें।",
        "invalid_pincode": "यह 6 अंकों का पिन कोड नहीं लग रहा। कृपया दोबारा भेजें।",
        "ask_roof_area": (
            "आपकी छत पर लगभग कितनी *खाली, बिना छाया वाली जगह* है (वर्ग फुट में)?\n"
            "अंदाज़ा भी चलेगा। पता न हो तो *DONT KNOW* लिखें।"
        ),
        "ask_sanctioned_load": (
            "आपके बिजली कनेक्शन का *स्वीकृत भार (sanctioned load)* कितना kW है?\n"
            "यह आपके बिल पर लिखा होता है। पता न हो तो *DONT KNOW* लिखें।"
        ),
        "ask_bills": (
            "कृपया अपने *पिछले 3 महीनों के बिजली बिल* रुपये में भेजें।\n"
            "उदाहरण: 1850 2100 1950"
        ),
        "invalid_bills": (
            "मैं वे राशियाँ नहीं पढ़ पाया। कृपया 3 संख्याएँ स्पेस देकर भेजें।\n"
            "उदाहरण: 1850 2100 1950"
        ),
        "ask_gst": "क्या आपका व्यापार *GST रजिस्टर्ड* है?\n1. हाँ\n2. नहीं",
        "ask_vintage": "आपका व्यापार कितने *वर्षों* से चल रहा है?",
        "ask_photo": (
            "आख़िरी कदम: कृपया अपनी *छत की एक फ़ोटो* भेजें, किसी एक कोने से ली हुई "
            "ताकि ज़्यादातर छत दिखे।\n"
            "इससे हम बिना इंजीनियर भेजे छाया की जाँच कर लेंगे।"
        ),
        "photo_received": "फ़ोटो मिल गई। अब आपका सोलर अनुमान निकाल रहा हूँ...",
        "photo_skipped": "कोई बात नहीं। सैटेलाइट डेटा से गणना कर रहा हूँ...",
        "computing": "कृपया एक क्षण रुकें, मैं गणना कर रहा हूँ...",
        "offer_residential": (
            "*आपका सोलर अनुमान*\n\n"
            "सुझाया गया सिस्टम: *{capacity} kW*\n"
            "अनुमानित लागत: ₹{gross_capex}\n"
            "पीएम सूर्य घर सब्सिडी: *- ₹{subsidy}*\n"
            "सब्सिडी के बाद आपकी लागत: ₹{net_capex}\n\n"
            "यदि आप लोन लेते हैं:\n"
            "मासिक EMI: ₹{emi}\n"
            "बिल में मासिक बचत: ₹{savings}\n"
            "*हर महीने शुद्ध लाभ: ₹{net_benefit}*\n\n"
            "लागत वसूली: लगभग *{payback} साल*। लोन ख़त्म होने के बाद 20+ साल तक "
            "पूरी बचत आपकी।"
        ),
        "offer_sme": (
            "*आपका सोलर अनुमान*\n\n"
            "सुझाया गया सिस्टम: *{capacity} kW*\n"
            "वार्षिक उत्पादन: {generation} यूनिट\n\n"
            "*विकल्प A - आप ख़रीदें (CAPEX)*\n"
            "निवेश: ₹{gross_capex}\n"
            "मासिक EMI: ₹{emi}\n"
            "मासिक बचत: ₹{savings}\n"
            "शुद्ध मासिक लाभ: *₹{net_benefit}*\n"
            "पहले साल त्वरित मूल्यह्रास से कर बचत: ₹{tax_shield}\n"
            "IRR: {irr}% | लागत वसूली: {payback} साल\n\n"
            "*विकल्प B - डेवलपर का स्वामित्व (OPEX / PPA)*\n"
            "आपका निवेश: *₹0*\n"
            "आप ₹{grid_tariff}/यूनिट की जगह केवल ₹{ppa_tariff}/यूनिट देंगे\n"
            "शुद्ध मासिक लाभ: *₹{opex_benefit}*\n\n"
            "हमारी सलाह: *{recommendation}*\n{rationale}"
        ),
        "ask_consent": (
            "क्या मैं आपको हमारे नज़दीकी प्रमाणित इंस्टॉलर से जोड़ दूँ? "
            "साइट विज़िट मुफ़्त है।\n1. हाँ, ज़रूर\n2. अभी नहीं"
        ),
        "routed": (
            "हो गया। *{partner}* आपसे {sla_hours} घंटे के भीतर संपर्क करेंगे।\n"
            "आपका संदर्भ नंबर: *{lead_id}*\n\n"
            "अगर उस समय में कोई संपर्क न करे तो *NO CONTACT* लिखकर भेजें।"
        ),
        "no_partner": (
            "आप योग्य हैं, लेकिन पिन कोड {pincode} में अभी हमारा प्रमाणित इंस्टॉलर "
            "नहीं है। हमने आपको प्रतीक्षा सूची में जोड़ दिया है। संदर्भ: *{lead_id}*"
        ),
        "declined": (
            "ठीक है। आपका अनुमान संदर्भ *{lead_id}* के तहत सुरक्षित है।\n"
            "जब चाहें *RESUME* लिखकर आगे बढ़ सकते हैं।"
        ),
        "dropped_unviable": (
            "आपके समय के लिए धन्यवाद। आपने जो जानकारी दी उसके आधार पर, अभी आपकी "
            "जगह पर सोलर सिस्टम अपनी लागत नहीं निकाल पाएगा।\n\n"
            "मुख्य कारण: {reason}\n\n"
            "हम आपको अभी सच बताना बेहतर समझते हैं बजाय किसी को भेजकर ऐसी चीज़ "
            "बेचने के जो काम न करे। बिजली खपत बढ़े तो *CHECK AGAIN* लिखें।"
        ),
        "fallback": (
            "क्षमा करें, मैं समझ नहीं पाया। {retry}\n\n"
            "दोबारा शुरू करने के लिए *RESTART* या किसी व्यक्ति से बात करने के लिए "
            "*HELP* लिखें।"
        ),
        "restart": "फिर से शुरू कर रहे हैं।",
        "help": "हमारी टीम का सदस्य जल्द ही आपको कॉल करेगा।",
        "resume": "वापस स्वागत है। जहाँ रुके थे वहीं से आगे बढ़ते हैं।",
        "session_expired": (
            "काफ़ी समय हो गया, इसलिए मैं नए सिरे से शुरू कर रहा हूँ ताकि आँकड़े "
            "ताज़ा रहें।"
        ),
        "escalated": (
            "बताने के लिए धन्यवाद। संदर्भ *{lead_id}* को हमने पार्टनर मैनेजर तक "
            "पहुँचा दिया है। {sla_hours} घंटे में कॉल आएगी।"
        ),
        "dont_know_ack": "कोई बात नहीं, मैं सैटेलाइट डेटा से अनुमान लगा लूँगा।",
    },

    "mr": {
        "ask_language": (
            "नमस्कार! मी RAAH, तुमचा सोलर सहाय्यक.\n"
            "कृपया तुमची भाषा निवडा:\n"
            "1. English\n2. हिन्दी\n3. मराठी\n4. ગુજરાતી\n5. தமிழ்"
        ),
        "ask_segment": (
            "हे तुमच्या *घरासाठी* आहे की *व्यवसाय/कारखान्यासाठी*?\n"
            "1. घर\n2. व्यवसाय / कारखाना / दुकान"
        ),
        "ask_ownership": (
            "हे छत *तुमच्या मालकीचे* आहे की भाड्याची मालमत्ता आहे?\n"
            "1. माझ्या मालकीचे\n2. भाड्याचे"
        ),
        "disqualify_rented": (
            "धन्यवाद. सोलर बसवण्यासाठी छताच्या मालकाची संमती लागते, त्यामुळे "
            "भाड्याच्या मालमत्तेवर आम्ही सध्या पुढे जाऊ शकत नाही.\n\n"
            "मालकाची लेखी संमती मिळाल्यास *OWNER OK* असे पाठवा."
        ),
        "ask_pincode": "कृपया तुमचा 6 अंकी *पिन कोड* पाठवा.",
        "invalid_pincode": "हा 6 अंकी पिन कोड वाटत नाही. कृपया पुन्हा पाठवा.",
        "ask_roof_area": (
            "तुमच्या छतावर अंदाजे किती *मोकळी, सावली नसलेली जागा* आहे (चौरस फूट)?\n"
            "अंदाज चालेल. माहीत नसल्यास *DONT KNOW* लिहा."
        ),
        "ask_sanctioned_load": (
            "तुमच्या वीज जोडणीचा *मंजूर भार (sanctioned load)* किती kW आहे?\n"
            "तो बिलावर छापलेला असतो. माहीत नसल्यास *DONT KNOW* लिहा."
        ),
        "ask_bills": (
            "कृपया तुमची *मागील 3 महिन्यांची वीज बिले* रुपयांत पाठवा.\n"
            "उदाहरण: 1850 2100 1950"
        ),
        "invalid_bills": (
            "मला त्या रकमा वाचता आल्या नाहीत. कृपया 3 आकडे स्पेस देऊन पाठवा.\n"
            "उदाहरण: 1850 2100 1950"
        ),
        "ask_gst": "तुमचा व्यवसाय *GST नोंदणीकृत* आहे का?\n1. होय\n2. नाही",
        "ask_vintage": "तुमचा व्यवसाय किती *वर्षांपासून* सुरू आहे?",
        "ask_photo": (
            "शेवटची पायरी: कृपया तुमच्या *छताचा फोटो* पाठवा, एका कोपऱ्यातून घेतलेला "
            "जेणेकरून बहुतांश छत दिसेल.\n"
            "यामुळे अभियंता न पाठवता आम्ही सावलीची तपासणी करू शकतो."
        ),
        "photo_received": "फोटो मिळाला. आता तुमचा सोलर अंदाज काढत आहे...",
        "photo_skipped": "हरकत नाही. उपग्रह डेटावरून गणना करत आहे...",
        "computing": "कृपया थोडा वेळ थांबा, मी आकडेमोड करत आहे...",
        "offer_residential": (
            "*तुमचा सोलर अंदाज*\n\n"
            "सुचवलेली प्रणाली: *{capacity} kW*\n"
            "अंदाजित खर्च: ₹{gross_capex}\n"
            "पीएम सूर्य घर अनुदान: *- ₹{subsidy}*\n"
            "अनुदानानंतर तुमचा खर्च: ₹{net_capex}\n\n"
            "कर्ज घेतल्यास:\n"
            "मासिक EMI: ₹{emi}\n"
            "बिलातील मासिक बचत: ₹{savings}\n"
            "*दर महिन्याचा निव्वळ फायदा: ₹{net_benefit}*\n\n"
            "परतावा कालावधी: सुमारे *{payback} वर्षे*. कर्ज संपल्यावर 20+ वर्षे "
            "संपूर्ण बचत तुमचीच."
        ),
        "offer_sme": (
            "*तुमचा सोलर अंदाज*\n\n"
            "सुचवलेली प्रणाली: *{capacity} kW*\n"
            "वार्षिक निर्मिती: {generation} युनिट\n\n"
            "*पर्याय A - तुम्ही खरेदी करा (CAPEX)*\n"
            "गुंतवणूक: ₹{gross_capex}\n"
            "मासिक EMI: ₹{emi}\n"
            "मासिक बचत: ₹{savings}\n"
            "निव्वळ मासिक फायदा: *₹{net_benefit}*\n"
            "पहिल्या वर्षी जलद घसाऱ्यातून कर बचत: ₹{tax_shield}\n"
            "IRR: {irr}% | परतावा: {payback} वर्षे\n\n"
            "*पर्याय B - डेव्हलपरची मालकी (OPEX / PPA)*\n"
            "तुमची गुंतवणूक: *₹0*\n"
            "तुम्ही ₹{grid_tariff}/युनिट ऐवजी फक्त ₹{ppa_tariff}/युनिट द्याल\n"
            "निव्वळ मासिक फायदा: *₹{opex_benefit}*\n\n"
            "आमची शिफारस: *{recommendation}*\n{rationale}"
        ),
        "ask_consent": (
            "मी तुम्हाला आमच्या जवळच्या प्रमाणित इंस्टॉलरशी जोडू का? "
            "साइट भेट मोफत आहे.\n1. होय\n2. आत्ता नको"
        ),
        "routed": (
            "झाले. *{partner}* तुमच्याशी {sla_hours} तासांत संपर्क करतील.\n"
            "तुमचा संदर्भ क्रमांक: *{lead_id}*\n\n"
            "त्या वेळेत कोणी संपर्क न केल्यास *NO CONTACT* असे पाठवा."
        ),
        "no_partner": (
            "तुम्ही पात्र आहात, परंतु पिन कोड {pincode} मध्ये सध्या आमचा प्रमाणित "
            "इंस्टॉलर नाही. तुम्हाला प्रतीक्षा यादीत जोडले आहे. संदर्भ: *{lead_id}*"
        ),
        "declined": (
            "समजले. तुमचा अंदाज संदर्भ *{lead_id}* अंतर्गत जतन केला आहे.\n"
            "कधीही *RESUME* लिहून पुढे जाऊ शकता."
        ),
        "dropped_unviable": (
            "तुमच्या वेळेबद्दल धन्यवाद. तुम्ही दिलेल्या माहितीनुसार, सध्या तुमच्या "
            "जागी सोलर प्रणाली स्वतःचा खर्च भरून काढणार नाही.\n\n"
            "मुख्य कारण: {reason}\n\n"
            "काम न करणारी गोष्ट विकण्यासाठी कोणाला पाठवण्यापेक्षा हे आत्ताच सांगणे "
            "आम्हाला योग्य वाटते. वीज वापर वाढल्यास *CHECK AGAIN* लिहा."
        ),
        "fallback": (
            "क्षमस्व, मला ते समजले नाही. {retry}\n\n"
            "पुन्हा सुरू करण्यासाठी *RESTART* किंवा व्यक्तीशी बोलण्यासाठी *HELP* लिहा."
        ),
        "restart": "पुन्हा सुरू करत आहे.",
        "help": "आमच्या टीमचा सदस्य लवकरच तुम्हाला कॉल करेल.",
        "resume": "पुन्हा स्वागत. जिथे थांबलो तिथून पुढे जाऊया.",
        "session_expired": (
            "बराच वेळ झाला, म्हणून आकडे ताजे राहावेत यासाठी मी नव्याने सुरू करतो."
        ),
        "escalated": (
            "कळवल्याबद्दल धन्यवाद. संदर्भ *{lead_id}* आमच्या पार्टनर मॅनेजरकडे "
            "पाठवला आहे. {sla_hours} तासांत कॉल येईल."
        ),
        "dont_know_ack": "हरकत नाही, मी उपग्रह डेटावरून अंदाज लावतो.",
    },

    "gu": {
        "ask_language": (
            "નમસ્તે! હું RAAH છું, તમારો સોલર સહાયક.\n"
            "કૃપા કરીને તમારી ભાષા પસંદ કરો:\n"
            "1. English\n2. हिन्दी\n3. मराठी\n4. ગુજરાતી\n5. தமிழ்"
        ),
        "ask_segment": (
            "આ તમારા *ઘર* માટે છે કે *ધંધા/ફેક્ટરી* માટે?\n"
            "1. ઘર\n2. ધંધો / ફેક્ટરી / દુકાન"
        ),
        "ask_ownership": (
            "આ છત *તમારી પોતાની* છે કે ભાડાની મિલકત છે?\n"
            "1. મારી પોતાની\n2. ભાડાની"
        ),
        "disqualify_rented": (
            "આભાર. સોલર લગાવવા માટે છતના માલિકની સંમતિ જરૂરી છે, તેથી ભાડાની "
            "મિલકત પર અમે અત્યારે આગળ વધી શકતા નથી.\n\n"
            "માલિકની લેખિત સંમતિ મળે તો *OWNER OK* લખીને મોકલો."
        ),
        "ask_pincode": "કૃપા કરીને તમારો 6 અંકનો *પિન કોડ* મોકલો.",
        "invalid_pincode": "આ 6 અંકનો પિન કોડ લાગતો નથી. કૃપા કરીને ફરી મોકલો.",
        "ask_roof_area": (
            "તમારી છત પર આશરે કેટલી *ખુલ્લી, છાંયડા વગરની જગ્યા* છે (ચોરસ ફૂટમાં)?\n"
            "અંદાજ પણ ચાલશે. ખબર ન હોય તો *DONT KNOW* લખો."
        ),
        "ask_sanctioned_load": (
            "તમારા વીજ જોડાણનો *મંજૂર ભાર (sanctioned load)* કેટલા kW છે?\n"
            "તે તમારા બિલ પર છપાયેલો હોય છે. ખબર ન હોય તો *DONT KNOW* લખો."
        ),
        "ask_bills": (
            "કૃપા કરીને તમારા *છેલ્લા 3 મહિનાના વીજ બિલ* રૂપિયામાં મોકલો.\n"
            "ઉદાહરણ: 1850 2100 1950"
        ),
        "invalid_bills": (
            "હું તે રકમો વાંચી શક્યો નહીં. કૃપા કરીને 3 આંકડા સ્પેસ આપીને મોકલો.\n"
            "ઉદાહરણ: 1850 2100 1950"
        ),
        "ask_gst": "શું તમારો ધંધો *GST રજિસ્ટર્ડ* છે?\n1. હા\n2. ના",
        "ask_vintage": "તમારો ધંધો કેટલા *વર્ષોથી* ચાલે છે?",
        "ask_photo": (
            "છેલ્લું પગલું: કૃપા કરીને તમારી *છતનો ફોટો* મોકલો, એક ખૂણેથી લીધેલો "
            "જેથી મોટા ભાગની છત દેખાય.\n"
            "આનાથી અમે ઇજનેર મોકલ્યા વગર છાંયડાની ચકાસણી કરી શકીશું."
        ),
        "photo_received": "ફોટો મળ્યો. હવે તમારો સોલર અંદાજ કાઢી રહ્યો છું...",
        "photo_skipped": "વાંધો નહીં. સેટેલાઇટ ડેટાથી ગણતરી કરી રહ્યો છું...",
        "computing": "કૃપા કરીને થોડી વાર રાહ જુઓ, હું ગણતરી કરી રહ્યો છું...",
        "offer_residential": (
            "*તમારો સોલર અંદાજ*\n\n"
            "સૂચવેલ સિસ્ટમ: *{capacity} kW*\n"
            "અંદાજિત ખર્ચ: ₹{gross_capex}\n"
            "પીએમ સૂર્ય ઘર સબસિડી: *- ₹{subsidy}*\n"
            "સબસિડી પછી તમારો ખર્ચ: ₹{net_capex}\n\n"
            "જો તમે લોન લો તો:\n"
            "માસિક EMI: ₹{emi}\n"
            "બિલમાં માસિક બચત: ₹{savings}\n"
            "*દર મહિને ચોખ્ખો ફાયદો: ₹{net_benefit}*\n\n"
            "ખર્ચ વસૂલાત: આશરે *{payback} વર્ષ*. લોન પૂરી થયા પછી 20+ વર્ષ સુધી "
            "આખી બચત તમારી."
        ),
        "offer_sme": (
            "*તમારો સોલર અંદાજ*\n\n"
            "સૂચવેલ સિસ્ટમ: *{capacity} kW*\n"
            "વાર્ષિક ઉત્પાદન: {generation} યુનિટ\n\n"
            "*વિકલ્પ A - તમે ખરીદો (CAPEX)*\n"
            "રોકાણ: ₹{gross_capex}\n"
            "માસિક EMI: ₹{emi}\n"
            "માસિક બચત: ₹{savings}\n"
            "ચોખ્ખો માસિક ફાયદો: *₹{net_benefit}*\n"
            "પ્રથમ વર્ષે ઝડપી ઘસારાથી કર બચત: ₹{tax_shield}\n"
            "IRR: {irr}% | વસૂલાત: {payback} વર્ષ\n\n"
            "*વિકલ્પ B - ડેવલપરની માલિકી (OPEX / PPA)*\n"
            "તમારું રોકાણ: *₹0*\n"
            "તમે ₹{grid_tariff}/યુનિટના બદલે માત્ર ₹{ppa_tariff}/યુનિટ ચૂકવશો\n"
            "ચોખ્ખો માસિક ફાયદો: *₹{opex_benefit}*\n\n"
            "અમારી ભલામણ: *{recommendation}*\n{rationale}"
        ),
        "ask_consent": (
            "શું હું તમને અમારા નજીકના પ્રમાણિત ઇન્સ્ટોલર સાથે જોડું? "
            "સાઇટ મુલાકાત મફત છે.\n1. હા\n2. અત્યારે નહીં"
        ),
        "routed": (
            "થઈ ગયું. *{partner}* તમારો {sla_hours} કલાકમાં સંપર્ક કરશે.\n"
            "તમારો સંદર્ભ નંબર: *{lead_id}*\n\n"
            "તે સમયમાં કોઈ સંપર્ક ન કરે તો *NO CONTACT* લખીને મોકલો."
        ),
        "no_partner": (
            "તમે લાયક છો, પરંતુ પિન કોડ {pincode} માં અત્યારે અમારો પ્રમાણિત "
            "ઇન્સ્ટોલર નથી. તમને પ્રતીક્ષા યાદીમાં ઉમેર્યા છે. સંદર્ભ: *{lead_id}*"
        ),
        "declined": (
            "સમજ્યો. તમારો અંદાજ સંદર્ભ *{lead_id}* હેઠળ સાચવ્યો છે.\n"
            "ગમે ત્યારે *RESUME* લખીને આગળ વધી શકો છો."
        ),
        "dropped_unviable": (
            "તમારા સમય બદલ આભાર. તમે આપેલી માહિતી પ્રમાણે, અત્યારે તમારી જગ્યાએ "
            "સોલર સિસ્ટમ પોતાનો ખર્ચ કાઢી શકશે નહીં.\n\n"
            "મુખ્ય કારણ: {reason}\n\n"
            "કામ ન કરે તેવી વસ્તુ વેચવા કોઈને મોકલવા કરતાં આ વાત અત્યારે કહેવી "
            "અમને યોગ્ય લાગે છે. વીજ વપરાશ વધે તો *CHECK AGAIN* લખો."
        ),
        "fallback": (
            "માફ કરશો, હું સમજ્યો નહીં. {retry}\n\n"
            "ફરી શરૂ કરવા *RESTART* અથવા વ્યક્તિ સાથે વાત કરવા *HELP* લખો."
        ),
        "restart": "ફરીથી શરૂ કરું છું.",
        "help": "અમારી ટીમનો સભ્ય ટૂંક સમયમાં તમને કૉલ કરશે.",
        "resume": "ફરી સ્વાગત છે. જ્યાં અટક્યા હતા ત્યાંથી આગળ વધીએ.",
        "session_expired": (
            "ઘણો સમય થઈ ગયો, તેથી આંકડા તાજા રહે તે માટે હું નવેસરથી શરૂ કરું છું."
        ),
        "escalated": (
            "જણાવવા બદલ આભાર. સંદર્ભ *{lead_id}* અમારા પાર્ટનર મેનેજરને મોકલ્યો છે. "
            "{sla_hours} કલાકમાં કૉલ આવશે."
        ),
        "dont_know_ack": "વાંધો નહીં, હું સેટેલાઇટ ડેટાથી અંદાજ લગાવીશ.",
    },

    "ta": {
        "ask_language": (
            "வணக்கம்! நான் RAAH, உங்கள் சூரிய ஆற்றல் உதவியாளர்.\n"
            "உங்கள் மொழியைத் தேர்ந்தெடுக்கவும்:\n"
            "1. English\n2. हिन्दी\n3. मराठी\n4. ગુજરાતી\n5. தமிழ்"
        ),
        "ask_segment": (
            "இது உங்கள் *வீட்டிற்கா* அல்லது *தொழில்/தொழிற்சாலைக்கா*?\n"
            "1. வீடு\n2. தொழில் / தொழிற்சாலை / கடை"
        ),
        "ask_ownership": (
            "இந்த மேற்கூரை *உங்களுடையதா* அல்லது வாடகைச் சொத்தா?\n"
            "1. என்னுடையது\n2. வாடகை"
        ),
        "disqualify_rented": (
            "நன்றி. சூரிய மின் அமைப்புக்கு மேற்கூரை உரிமையாளரின் ஒப்புதல் தேவை, "
            "எனவே வாடகைச் சொத்தில் இப்போது தொடர முடியாது.\n\n"
            "உரிமையாளரின் எழுத்துப்பூர்வ ஒப்புதல் கிடைத்தால் *OWNER OK* என அனுப்பவும்."
        ),
        "ask_pincode": "உங்கள் 6 இலக்க *பின் கோடை* அனுப்பவும்.",
        "invalid_pincode": "இது 6 இலக்க பின் கோடாகத் தெரியவில்லை. மீண்டும் அனுப்பவும்.",
        "ask_roof_area": (
            "உங்கள் மேற்கூரையில் தோராயமாக எவ்வளவு *திறந்த, நிழலற்ற இடம்* உள்ளது "
            "(சதுர அடியில்)?\nதோராயம் போதும். தெரியவில்லை என்றால் *DONT KNOW* எனத் தட்டவும்."
        ),
        "ask_sanctioned_load": (
            "உங்கள் மின் இணைப்பின் *அனுமதிக்கப்பட்ட சுமை (sanctioned load)* எத்தனை kW?\n"
            "இது உங்கள் பில்லில் அச்சிடப்பட்டிருக்கும். தெரியவில்லை என்றால் *DONT KNOW*."
        ),
        "ask_bills": (
            "உங்கள் *கடந்த 3 மாத மின் கட்டணத்* தொகைகளை ரூபாயில் அனுப்பவும்.\n"
            "எடுத்துக்காட்டு: 1850 2100 1950"
        ),
        "invalid_bills": (
            "அந்தத் தொகைகளை என்னால் படிக்க முடியவில்லை. 3 எண்களை இடைவெளியுடன் அனுப்பவும்.\n"
            "எடுத்துக்காட்டு: 1850 2100 1950"
        ),
        "ask_gst": "உங்கள் தொழில் *GST பதிவு* செய்யப்பட்டதா?\n1. ஆம்\n2. இல்லை",
        "ask_vintage": "உங்கள் தொழில் எத்தனை *ஆண்டுகளாக* இயங்குகிறது?",
        "ask_photo": (
            "கடைசிப் படி: உங்கள் *மேற்கூரையின் புகைப்படத்தை* அனுப்பவும், ஒரு மூலையில் "
            "இருந்து எடுக்கப்பட்டது, பெரும்பாலான மேற்கூரை தெரியும்படி.\n"
            "இதனால் பொறியாளரை அனுப்பாமலேயே நிழலைச் சரிபார்க்க முடியும்."
        ),
        "photo_received": "புகைப்படம் கிடைத்தது. உங்கள் சூரிய மதிப்பீட்டைக் கணக்கிடுகிறேன்...",
        "photo_skipped": "பரவாயில்லை. செயற்கைக்கோள் தரவைக் கொண்டு கணக்கிடுகிறேன்...",
        "computing": "சற்று காத்திருக்கவும், கணக்கிட்டுக் கொண்டிருக்கிறேன்...",
        "offer_residential": (
            "*உங்கள் சூரிய மதிப்பீடு*\n\n"
            "பரிந்துரைக்கப்பட்ட அமைப்பு: *{capacity} kW*\n"
            "மதிப்பிடப்பட்ட செலவு: ₹{gross_capex}\n"
            "பிஎம் சூர்ய கர் மானியம்: *- ₹{subsidy}*\n"
            "மானியத்திற்குப் பிறகு உங்கள் செலவு: ₹{net_capex}\n\n"
            "கடன் பெற்றால்:\n"
            "மாதத் தவணை (EMI): ₹{emi}\n"
            "மாதாந்திர பில் சேமிப்பு: ₹{savings}\n"
            "*ஒவ்வொரு மாதமும் நிகர பலன்: ₹{net_benefit}*\n\n"
            "முதலீட்டு மீட்பு: சுமார் *{payback} ஆண்டுகள்*. கடன் முடிந்த பிறகு 20+ "
            "ஆண்டுகளுக்கு முழுச் சேமிப்பும் உங்களுடையது."
        ),
        "offer_sme": (
            "*உங்கள் சூரிய மதிப்பீடு*\n\n"
            "பரிந்துரைக்கப்பட்ட அமைப்பு: *{capacity} kW*\n"
            "ஆண்டு உற்பத்தி: {generation} யூனிட்\n\n"
            "*விருப்பம் A - நீங்கள் வாங்குதல் (CAPEX)*\n"
            "முதலீடு: ₹{gross_capex}\n"
            "மாதத் தவணை: ₹{emi}\n"
            "மாதாந்திர சேமிப்பு: ₹{savings}\n"
            "நிகர மாதாந்திர பலன்: *₹{net_benefit}*\n"
            "முதல் ஆண்டு துரித தேய்மானத்தால் வரிச் சேமிப்பு: ₹{tax_shield}\n"
            "IRR: {irr}% | மீட்பு: {payback} ஆண்டுகள்\n\n"
            "*விருப்பம் B - டெவலப்பர் உரிமை (OPEX / PPA)*\n"
            "உங்கள் முதலீடு: *₹0*\n"
            "₹{grid_tariff}/யூனிட்டுக்குப் பதிலாக ₹{ppa_tariff}/யூனிட் மட்டுமே\n"
            "நிகர மாதாந்திர பலன்: *₹{opex_benefit}*\n\n"
            "எங்கள் பரிந்துரை: *{recommendation}*\n{rationale}"
        ),
        "ask_consent": (
            "எங்கள் அருகிலுள்ள சான்றளிக்கப்பட்ட நிறுவுநருடன் உங்களை இணைக்கவா? "
            "தள வருகை இலவசம்.\n1. ஆம்\n2. இப்போது வேண்டாம்"
        ),
        "routed": (
            "முடிந்தது. *{partner}* {sla_hours} மணி நேரத்திற்குள் உங்களைத் தொடர்பு கொள்வார்.\n"
            "உங்கள் குறிப்பு எண்: *{lead_id}*\n\n"
            "அந்த நேரத்தில் யாரும் தொடர்பு கொள்ளாவிட்டால் *NO CONTACT* என அனுப்பவும்."
        ),
        "no_partner": (
            "நீங்கள் தகுதி பெற்றுள்ளீர்கள், ஆனால் பின் கோடு {pincode} இல் இன்னும் "
            "எங்கள் சான்றளிக்கப்பட்ட நிறுவுநர் இல்லை. காத்திருப்புப் பட்டியலில் "
            "சேர்த்துள்ளோம். குறிப்பு: *{lead_id}*"
        ),
        "declined": (
            "புரிந்தது. உங்கள் மதிப்பீடு குறிப்பு *{lead_id}* இல் சேமிக்கப்பட்டுள்ளது.\n"
            "எப்போது வேண்டுமானாலும் *RESUME* என அனுப்பி தொடரலாம்."
        ),
        "dropped_unviable": (
            "உங்கள் நேரத்திற்கு நன்றி. நீங்கள் பகிர்ந்ததன் அடிப்படையில், இப்போது "
            "உங்கள் இடத்தில் சூரிய அமைப்பு அதன் செலவை ஈடுகட்டாது.\n\n"
            "முக்கியக் காரணம்: {reason}\n\n"
            "வேலை செய்யாத ஒன்றை விற்க ஆளை அனுப்புவதை விட இதை இப்போதே சொல்வதையே "
            "நாங்கள் விரும்புகிறோம். மின் பயன்பாடு அதிகரித்தால் *CHECK AGAIN* எனத் தட்டவும்."
        ),
        "fallback": (
            "மன்னிக்கவும், எனக்குப் புரியவில்லை. {retry}\n\n"
            "மீண்டும் தொடங்க *RESTART* அல்லது ஒருவரிடம் பேச *HELP* எனத் தட்டவும்."
        ),
        "restart": "மீண்டும் தொடங்குகிறேன்.",
        "help": "எங்கள் குழு உறுப்பினர் விரைவில் உங்களை அழைப்பார்.",
        "resume": "மீண்டும் வரவேற்கிறோம். நிறுத்திய இடத்திலிருந்து தொடரலாம்.",
        "session_expired": (
            "நீண்ட நேரம் ஆகிவிட்டது, எனவே எண்கள் புதியதாக இருக்க புதிதாகத் தொடங்குகிறேன்."
        ),
        "escalated": (
            "தெரிவித்ததற்கு நன்றி. குறிப்பு *{lead_id}* எங்கள் பார்ட்னர் மேனேஜரிடம் "
            "அனுப்பப்பட்டுள்ளது. {sla_hours} மணி நேரத்தில் அழைப்பு வரும்."
        ),
        "dont_know_ack": "பரவாயில்லை, செயற்கைக்கோள் தரவைக் கொண்டு மதிப்பிடுகிறேன்.",
    },
}


def t(language: str, key: str, **kwargs) -> str:
    """
    Translate. Falls back to English for a missing key or language so a
    partial translation never breaks the conversation.
    """
    language = (language or DEFAULT_LANGUAGE).lower()
    bundle = MESSAGES.get(language, MESSAGES[DEFAULT_LANGUAGE])
    template = bundle.get(key) or MESSAGES[DEFAULT_LANGUAGE].get(key, key)

    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except KeyError:
        return template


# Reasons shown when a lead is dropped. Kept separate from the flow so the
# customer-facing wording can be tuned without touching decision logic.
DROP_REASONS = {
    "en": {
        "rented_roof": "the roof is rented and owner consent is not available",
        "low_consumption": "your electricity usage is too low for the system to pay back",
        "tiny_roof": "the available shadow-free roof area is too small for a viable system",
        "heavy_shading": "too much of the roof is in shadow through the day",
        "poor_economics": "the payback period is longer than we consider fair to recommend",
        "emi_exceeds_savings": "the monthly EMI would be higher than your monthly savings",
    },
    "hi": {
        "rented_roof": "छत किराये की है और मालिक की अनुमति उपलब्ध नहीं है",
        "low_consumption": "आपकी बिजली खपत इतनी कम है कि लागत वसूल नहीं होगी",
        "tiny_roof": "बिना छाया वाली छत की जगह इतनी कम है कि सिस्टम व्यवहार्य नहीं",
        "heavy_shading": "दिन भर छत का बड़ा हिस्सा छाया में रहता है",
        "poor_economics": "लागत वसूली की अवधि इतनी लंबी है कि सुझाव देना उचित नहीं",
        "emi_exceeds_savings": "मासिक EMI आपकी मासिक बचत से ज़्यादा होगी",
    },
    "mr": {
        "rented_roof": "छत भाड्याची आहे आणि मालकाची संमती उपलब्ध नाही",
        "low_consumption": "तुमचा वीज वापर इतका कमी आहे की खर्च वसूल होणार नाही",
        "tiny_roof": "सावली नसलेली छताची जागा प्रणालीसाठी खूपच कमी आहे",
        "heavy_shading": "दिवसभर छताचा मोठा भाग सावलीत राहतो",
        "poor_economics": "परतावा कालावधी शिफारस करण्याइतका वाजवी नाही",
        "emi_exceeds_savings": "मासिक EMI तुमच्या मासिक बचतीपेक्षा जास्त होईल",
    },
    "gu": {
        "rented_roof": "છત ભાડાની છે અને માલિકની સંમતિ ઉપલબ્ધ નથી",
        "low_consumption": "તમારો વીજ વપરાશ એટલો ઓછો છે કે ખર્ચ વસૂલ નહીં થાય",
        "tiny_roof": "છાંયડા વગરની છતની જગ્યા સિસ્ટમ માટે ઘણી ઓછી છે",
        "heavy_shading": "દિવસભર છતનો મોટો ભાગ છાંયડામાં રહે છે",
        "poor_economics": "ખર્ચ વસૂલાતનો સમયગાળો ભલામણ કરવા જેટલો વાજબી નથી",
        "emi_exceeds_savings": "માસિક EMI તમારી માસિક બચત કરતાં વધુ થશે",
    },
    "ta": {
        "rented_roof": "மேற்கூரை வாடகைக்கு உள்ளது, உரிமையாளர் ஒப்புதல் இல்லை",
        "low_consumption": "உங்கள் மின் பயன்பாடு மிகக் குறைவு, முதலீடு ஈடுகட்டாது",
        "tiny_roof": "நிழலற்ற மேற்கூரைப் பரப்பு அமைப்புக்கு மிகச் சிறியது",
        "heavy_shading": "நாள் முழுவதும் மேற்கூரையின் பெரும்பகுதி நிழலில் உள்ளது",
        "poor_economics": "முதலீட்டு மீட்புக் காலம் பரிந்துரைக்கும் அளவுக்கு நியாயமானது அல்ல",
        "emi_exceeds_savings": "மாதத் தவணை உங்கள் மாதாந்திர சேமிப்பை விட அதிகமாக இருக்கும்",
    },
}


def drop_reason(language: str, code: str) -> str:
    language = (language or DEFAULT_LANGUAGE).lower()
    bundle = DROP_REASONS.get(language, DROP_REASONS[DEFAULT_LANGUAGE])
    return bundle.get(code) or DROP_REASONS[DEFAULT_LANGUAGE].get(code, code)