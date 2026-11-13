/* Triyana — app languages: English, Hindi, Telugu, Tamil.
   Screens are written in English; this file swaps known phrases for the chosen language as they appear
   (text, placeholders, labels), so every screen picks it up without changing how screens are built.
   Translations are a first pass for the demo and should be checked by native speakers before launch. */
"use strict";

const LANGS = [["en", "English", "EN"], ["hi", "हिन्दी", "हि"], ["te", "తెలుగు", "తె"], ["ta", "தமிழ்", "த"]];
const LANG_KEY = "triyana.lang";
let LANG = "en";
try { LANG = localStorage.getItem(LANG_KEY) || "en"; } catch {}
if (!LANGS.some((l) => l[0] === LANG)) LANG = "en";

// [English, Hindi, Telugu, Tamil]
const PHRASES = [
  // brand, shell, navigation
  ["Doctor at home in 10 min", "10 मिनट में घर पर डॉक्टर", "10 నిమిషాల్లో ఇంటికి డాక్టర్", "10 நிமிடத்தில் வீட்டுக்கு டாக்டர்"],
  ["Home", "होम", "హోమ్", "முகப்பு"],
  ["Shop", "दुकान", "షాప్", "கடை"],
  ["Book a doctor", "डॉक्टर बुक करें", "డాక్టర్‌ను బుక్ చేయండి", "டாக்டரை புக் செய்யுங்கள்"],
  ["Doctor", "डॉक्टर", "డాక్టర్", "டாக்டர்"],
  ["Prescription", "पर्चा", "ప్రిస్క్రిప్షన్", "மருந்துச் சீட்டு"],
  ["Rx", "पर्चा", "ప్రిస్క్రిప్షన్", "சீட்டு"],
  ["Cart", "कार्ट", "కార్ట్", "கார்ட்"],
  ["Pharmacies", "दवा दुकानें", "ఫార్మసీలు", "மருந்தகங்கள்"],
  ["Tracking", "ट्रैकिंग", "ట్రాకింగ్", "கண்காணிப்பு"],
  ["Track", "ट्रैक", "ట్రాక్", "கண்காணி"],
  ["My Medicines", "मेरी दवाइयाँ", "నా మందులు", "என் மருந்துகள்"],
  ["Medicines", "दवाइयाँ", "మందులు", "மருந்துகள்"],
  ["Privacy & consent", "गोपनीयता और सहमति", "గోప్యత & సమ్మతి", "தனியுரிமை & ஒப்புதல்"],
  ["Account", "खाता", "ఖాతా", "கணக்கு"],
  ["Health records", "स्वास्थ्य रिकॉर्ड", "ఆరోగ్య రికార్డులు", "உடல்நலப் பதிவுகள்"],
  ["Records", "रिकॉर्ड", "రికార్డులు", "பதிவுகள்"],
  ["Care plans", "केयर प्लान", "కేర్ ప్లాన్‌లు", "பராமரிப்புத் திட்டங்கள்"],
  ["Plans", "प्लान", "ప్లాన్‌లు", "திட்டங்கள்"],
  ["Sign out", "साइन आउट", "సైన్ అవుట్", "வெளியேறு"],
  ["Signed in as", "साइन इन", "సైన్ ఇన్ అయినది", "உள்நுழைந்தவர்"],
  ["Language", "भाषा", "భాష", "மொழி"],
  // home
  ["Need a doctor? One at your door in 10 minutes.", "डॉक्टर चाहिए? 10 मिनट में आपके दरवाज़े पर।", "డాక్టర్ కావాలా? 10 నిమిషాల్లో మీ ఇంటి ముందు.", "டாக்டர் வேண்டுமா? 10 நிமிடத்தில் உங்கள் வீட்டு வாசலில்."],
  ["A verified doctor comes to your home, checks you, and prescribes. Your medicines are delivered to your door.", "सत्यापित डॉक्टर आपके घर आते हैं, जाँच करते हैं और दवा लिखते हैं। दवाइयाँ आपके घर पहुँचाई जाती हैं।", "ధృవీకరించిన డాక్టర్ మీ ఇంటికి వచ్చి పరీక్షించి మందులు రాస్తారు. మందులు మీ ఇంటికే అందుతాయి.", "சரிபார்க்கப்பட்ட டாக்டர் உங்கள் வீட்டுக்கு வந்து பரிசோதித்து மருந்து எழுதுவார். மருந்துகள் வீட்டுக்கே வரும்."],
  ["Doctor in 10 min", "10 मिनट में डॉक्टर", "10 నిమిషాల్లో డాక్టర్", "10 நிமிடத்தில் டாக்டர்"],
  ["Book a home visit", "घर पर विज़िट बुक करें", "ఇంటి విజిట్ బుక్ చేయండి", "வீட்டு வருகையை புக் செய்யுங்கள்"],
  ["Book by voice", "बोलकर बुक करें", "మాట్లాడి బుక్ చేయండి", "பேசி புக் செய்யுங்கள்"],
  ["Upcoming visits", "आने वाली विज़िट", "రాబోయే విజిట్‌లు", "வரவிருக்கும் வருகைகள்"],
  ["Active prescriptions", "चालू पर्चे", "ప్రస్తుత ప్రిస్క్రిప్షన్‌లు", "நடப்பு மருந்துச் சீட்டுகள்"],
  ["Orders in progress", "चल रहे ऑर्डर", "జరుగుతున్న ఆర్డర్‌లు", "நடப்பில் உள்ள ஆர்டர்கள்"],
  ["Services", "सेवाएँ", "సేవలు", "சேவைகள்"],
  ["Notifications", "सूचनाएँ", "నోటిఫికేషన్‌లు", "அறிவிப்புகள்"],
  ["You're all caught up.", "कोई नई सूचना नहीं।", "కొత్తవి ఏమీ లేవు.", "புதிதாக எதுவும் இல்லை."],
  ["Visit history", "पिछली विज़िट", "గత విజిట్‌లు", "முந்தைய வருகைகள்"],
  ["Your upcoming visit", "आपकी अगली विज़िट", "మీ తదుపరి విజిట్", "உங்கள் அடுத்த வருகை"],
  ["Your upcoming visits", "आपकी आने वाली विज़िट", "మీ రాబోయే విజిట్‌లు", "உங்கள் வரவிருக்கும் வருகைகள்"],
  ["Live map", "लाइव मैप", "లైవ్ మ్యాప్", "நேரலை வரைபடம்"],
  ["Track live", "लाइव देखें", "లైవ్‌గా చూడండి", "நேரலையில் பாருங்கள்"],
  ["Cancel booking", "बुकिंग रद्द करें", "బుకింగ్ రద్దు చేయండి", "புக்கிங்கை ரத்து செய்"],
  ["View visit notes", "विज़िट नोट्स देखें", "విజిట్ నోట్స్ చూడండి", "வருகைக் குறிப்புகளைப் பார்"],
  ["Completed", "पूरा हुआ", "పూర్తయింది", "முடிந்தது"],
  ["Confirmed", "पक्का", "ఖరారైంది", "உறுதியானது"],
  ["Waiting for doctor to confirm", "डॉक्टर की पुष्टि का इंतज़ार", "డాక్టర్ నిర్ధారణ కోసం వేచి ఉంది", "டாக்டர் உறுதிப்படுத்தக் காத்திருக்கிறது"],
  ["Doctor is with you", "डॉक्टर आपके पास हैं", "డాక్టర్ మీ దగ్గర ఉన్నారు", "டாக்டர் உங்களுடன் இருக்கிறார்"],
  ["Cancelled", "रद्द", "రద్దయింది", "ரத்தானது"],
  ["Reason:", "कारण:", "కారణం:", "காரணம்:"],
  ["Diagnosis:", "निदान:", "నిర్ధారణ:", "நோயறிதல்:"],
  ["pay after the visit", "विज़िट के बाद भुगतान", "విజిట్ తర్వాత చెల్లించండి", "வருகைக்குப் பிறகு செலுத்துங்கள்"],
  ["covered by your care plan", "आपके केयर प्लान में शामिल", "మీ కేర్ ప్లాన్‌లో భాగం", "உங்கள் பராமரிப்புத் திட்டத்தில் அடங்கும்"],
  ["Follow-up", "फॉलो-अप", "ఫాలో-అప్", "தொடர் வருகை"],
  // services
  ["10-MINUTE DOCTOR", "10 मिनट डॉक्टर", "10 నిమిషాల డాక్టర్", "10 நிமிட டாக்டர்"],
  ["A doctor at your door in 10 minutes", "10 मिनट में आपके दरवाज़े पर डॉक्टर", "10 నిమిషాల్లో మీ ఇంటి ముందు డాక్టర్", "10 நிமிடத்தில் உங்கள் வாசலில் டாக்டர்"],
  ["One tap. The nearest verified doctor accepts, passes a live face check and comes to your home. Watch them arrive on the map.", "एक टैप। सबसे नज़दीकी सत्यापित डॉक्टर स्वीकार करते हैं, चेहरे की जाँच पास करते हैं और आपके घर आते हैं। मैप पर उन्हें आते देखें।", "ఒక్క ట్యాప్. దగ్గరలోని ధృవీకరించిన డాక్టర్ అంగీకరించి, ముఖ తనిఖీ తర్వాత మీ ఇంటికి వస్తారు. మ్యాప్‌లో చూడండి.", "ஒரே தட்டல். அருகிலுள்ள சரிபார்க்கப்பட்ட டாக்டர் ஏற்று, முக சோதனைக்குப் பின் உங்கள் வீட்டுக்கு வருவார். வரைபடத்தில் பாருங்கள்."],
  ["Get a doctor in 10 min", "10 मिनट में डॉक्टर पाएँ", "10 నిమిషాల్లో డాక్టర్ పొందండి", "10 நிமிடத்தில் டாக்டரைப் பெறுங்கள்"],
  ["Physiotherapy at home", "घर पर फिज़ियोथेरेपी", "ఇంట్లో ఫిజియోథెరపీ", "வீட்டில் பிசியோதெரபி"],
  ["Book physio", "फिज़ियो बुक करें", "ఫిజియో బుక్ చేయండి", "பிசியோ புக் செய்"],
  ["Medicine shop", "दवा की दुकान", "మందుల షాప్", "மருந்துக் கடை"],
  ["Rider delivery in under an hour", "एक घंटे के अंदर डिलीवरी", "గంటలోపు డెలివరీ", "ஒரு மணி நேரத்தில் டெலிவரி"],
  ["Pick a doctor and a time", "डॉक्टर और समय चुनें", "డాక్టర్‌ను, సమయాన్ని ఎంచుకోండి", "டாக்டரையும் நேரத்தையும் தேர்ந்தெடுங்கள்"],
  ["Physio at home", "घर पर फिज़ियो", "ఇంట్లో ఫిజియో", "வீட்டில் பிசியோ"],
  ["Sessions & packages, live map", "सेशन और पैकेज, लाइव मैप", "సెషన్‌లు & ప్యాకేజీలు, లైవ్ మ్యాప్", "அமர்வுகள் & தொகுப்புகள், நேரலை வரைபடம்"],
  ["Lab tests at home", "घर पर लैब टेस्ट", "ఇంట్లో ల్యాబ్ పరీక్షలు", "வீட்டில் ஆய்வகப் பரிசோதனைகள்"],
  ["Collector at your door, reports here", "सैंपल घर से, रिपोर्ट यहाँ", "ఇంటి వద్దే శాంపిల్, రిపోర్ట్ ఇక్కడే", "வீட்டிலேயே மாதிரி, அறிக்கை இங்கே"],
  ["Prescriptions", "पर्चे", "ప్రిస్క్రిప్షన్‌లు", "மருந்துச் சீட்டுகள்"],
  ["E-signed by your doctor", "डॉक्टर के ई-हस्ताक्षर सहित", "డాక్టర్ ఇ-సంతకంతో", "டாக்டரின் மின்-கையொப்பத்துடன்"],
  ["Medicine cart", "दवा कार्ट", "మందుల కార్ట్", "மருந்துக் கார்ட்"],
  ["Choose what to buy, and how much", "क्या और कितना खरीदना है चुनें", "ఏమి, ఎంత కొనాలో ఎంచుకోండి", "எதை, எவ்வளவு வாங்குவது என்று தேர்ந்தெடுங்கள்"],
  ["Track orders", "ऑर्डर ट्रैक करें", "ఆర్డర్‌లు ట్రాక్ చేయండి", "ஆர்டர்களைக் கண்காணி"],
  ["Live courier map", "लाइव कूरियर मैप", "లైవ్ కొరియర్ మ్యాప్", "நேரலை கூரியர் வரைபடம்"],
  ["Prescribed, ordered, dispensed", "लिखी, मँगाई, मिली दवाइयाँ", "రాసినవి, ఆర్డర్ చేసినవి, అందినవి", "எழுதியவை, ஆர்டர் செய்தவை, வழங்கியவை"],
  ["Ask Yana", "याना से पूछें", "యానాను అడగండి", "யானாவிடம் கேளுங்கள்"],
  ["Your medicine assistant", "आपकी दवा सहायक", "మీ మందుల సహాయకురాలు", "உங்கள் மருந்து உதவியாளர்"],
  ["Just say what's wrong, in your language", "अपनी भाषा में बताइए क्या तकलीफ़ है", "మీ భాషలో సమస్య చెప్పండి", "உங்கள் மொழியில் பிரச்சனையைச் சொல்லுங்கள்"],
  ["Monthly home check-ups: diabetes, BP, elders", "हर महीने घर पर जाँच: शुगर, बीपी, बुज़ुर्ग", "నెలవారీ ఇంటి చెకప్‌లు: షుగర్, బీపీ, పెద్దలు", "மாதாந்திர வீட்டுப் பரிசோதனை: சர்க்கரை, பிபி, முதியோர்"],
  ["Visits, vitals, labs and prescriptions", "विज़िट, वाइटल्स, लैब और पर्चे", "విజిట్‌లు, వైటల్స్, ల్యాబ్, ప్రిస్క్రిప్షన్‌లు", "வருகைகள், உயிர்க்குறிகள், ஆய்வகம், மருந்துச் சீட்டுகள்"],
  // reasons
  ["Fever or cold", "बुखार या सर्दी", "జ్వరం లేదా జలుబు", "காய்ச்சல் அல்லது சளி"],
  ["General check-up", "सामान्य जाँच", "సాధారణ చెకప్", "பொதுப் பரிசோதனை"],
  ["Child is unwell", "बच्चा बीमार है", "పిల్లలకు బాగాలేదు", "குழந்தைக்கு உடல்நலமில்லை"],
  ["Elderly parent care", "बुज़ुर्ग माता-पिता की देखभाल", "వృద్ధ తల్లిదండ్రుల సంరక్షణ", "வயதான பெற்றோர் பராமரிப்பு"],
  ["Joint or back pain", "जोड़ों या कमर का दर्द", "కీళ్ల లేదా నడుము నొప్పి", "மூட்டு அல்லது முதுகு வலி"],
  ["Follow-up visit", "फॉलो-अप विज़िट", "ఫాలో-అప్ విజిట్", "தொடர் வருகை"],
  ["Blood pressure check", "बीपी जाँच", "బీపీ పరీక్ష", "இரத்த அழுத்தப் பரிசோதனை"],
  ["Sugar (diabetes) check", "शुगर जाँच", "షుగర్ పరీక్ష", "சர்க்கரைப் பரிசோதனை"],
  ["Stomach upset", "पेट ख़राब", "కడుపు నొప్పి", "வயிற்றுக் கோளாறு"],
  // doctor now sheet
  ["Doctor now", "अभी डॉक्टर", "ఇప్పుడే డాక్టర్", "இப்போதே டாக்டர்"],
  ["Tell the doctor more (optional)", "डॉक्टर को और बताएँ (ज़रूरी नहीं)", "డాక్టర్‌కు మరింత చెప్పండి (ఐచ్ఛికం)", "டாக்டரிடம் மேலும் சொல்லுங்கள் (விருப்பம்)"],
  ["Visit address", "पता", "చిరునామా", "முகவரி"],
  ["Book a time instead", "बजाय इसके समय बुक करें", "బదులుగా సమయం బుక్ చేయండి", "பதிலாக நேரம் புக் செய்யுங்கள்"],
  // care plans
  ["Regular doctor check-ups at home for long-term conditions. We book every visit for you.", "लंबी बीमारियों के लिए घर पर नियमित जाँच। हर विज़िट हम बुक करते हैं।", "దీర్ఘకాలిక వ్యాధులకు ఇంట్లో క్రమం తప్పని చెకప్‌లు. ప్రతి విజిట్ మేమే బుక్ చేస్తాం.", "நீண்டகால நோய்களுக்கு வீட்டில் வழக்கமான பரிசோதனை. ஒவ்வொரு வருகையையும் நாங்களே புக் செய்கிறோம்."],
  ["Choose a plan", "प्लान चुनें", "ప్లాన్ ఎంచుకోండి", "திட்டத்தைத் தேர்ந்தெடுங்கள்"],
  ["Add another plan", "एक और प्लान जोड़ें", "మరో ప్లాన్ జోడించండి", "மற்றொரு திட்டம் சேர்"],
  ["Start plan", "प्लान शुरू करें", "ప్లాన్ ప్రారంభించండి", "திட்டத்தைத் தொடங்கு"],
  ["You have this plan", "यह प्लान आपके पास है", "ఈ ప్లాన్ మీకు ఉంది", "இந்தத் திட்டம் உங்களிடம் உள்ளது"],
  ["Active", "चालू", "యాక్టివ్", "செயலில்"],
  ["Cancel plan", "प्लान रद्द करें", "ప్లాన్ రద్దు చేయండి", "திட்டத்தை ரத்து செய்"],
  ["+ a free doctor call within 48 hours of every visit", "+ हर विज़िट के 48 घंटे में डॉक्टर का मुफ़्त कॉल", "+ ప్రతి విజిట్ తర్వాత 48 గంటల్లో డాక్టర్ ఉచిత కాల్", "+ ஒவ்வொரு வருகைக்கும் 48 மணி நேரத்தில் டாக்டரின் இலவச அழைப்பு"],
  ["What time suits you for check-ups?", "जाँच के लिए कौन सा समय ठीक है?", "చెకప్‌లకు ఏ సమయం సరిపోతుంది?", "பரிசோதனைக்கு எந்த நேரம் வசதி?"],
  ["Diabetes care", "शुगर केयर", "షుగర్ కేర్", "சர்க்கரை பராமரிப்பு"],
  ["Blood pressure care", "बीपी केयर", "బీపీ కేర్", "இரத்த அழுத்தப் பராமரிப்பு"],
  ["Bedridden patient care", "बिस्तर पर मरीज़ की देखभाल", "మంచం మీద ఉన్న రోగి సంరక్షణ", "படுக்கை நோயாளி பராமரிப்பு"],
  ["Senior wellness", "बुज़ुर्ग स्वास्थ्य", "పెద్దల ఆరోగ్యం", "முதியோர் நலம்"],
  ["Type 1 or type 2 diabetes, on tablets or insulin", "टाइप 1 या 2 शुगर, गोली या इंसुलिन पर", "టైప్ 1 లేదా 2 షుగర్, మాత్రలు లేదా ఇన్సులిన్", "வகை 1 அல்லது 2 சர்க்கரை, மாத்திரை அல்லது இன்சுலின்"],
  ["High blood pressure or heart patients", "हाई बीपी या दिल के मरीज़", "అధిక బీపీ లేదా గుండె రోగులు", "உயர் இரத்த அழுத்தம் அல்லது இதய நோயாளிகள்"],
  ["Patients who can't leave bed: after a stroke, surgery or long illness", "बिस्तर से न उठ पाने वाले मरीज़: लकवा, ऑपरेशन या लंबी बीमारी के बाद", "మంచం దిగలేని రోగులు: పక్షవాతం, శస్త్రచికిత్స లేదా దీర్ఘ అనారోగ్యం తర్వాత", "படுக்கையை விட்டு எழ முடியாதவர்கள்: பக்கவாதம், அறுவை சிகிச்சை அல்லது நீண்ட நோய்க்குப் பின்"],
  ["Parents and grandparents over 60", "60 साल से ऊपर के माता-पिता और दादा-दादी", "60 ఏళ్లు పైబడిన తల్లిదండ్రులు, తాతయ్య-అమ్మమ్మలు", "60 வயதுக்கு மேற்பட்ட பெற்றோர், தாத்தா பாட்டி"],
  // follow-up calls
  ["Free follow-up call", "मुफ़्त फॉलो-अप कॉल", "ఉచిత ఫాలో-అప్ కాల్", "இலவச தொடர் அழைப்பு"],
  ["How are you feeling since the visit?", "विज़िट के बाद अब आप कैसा महसूस कर रहे हैं?", "విజిట్ తర్వాత మీకు ఎలా ఉంది?", "வருகைக்குப் பிறகு எப்படி இருக்கிறீர்கள்?"],
  ["Better", "बेहतर", "మెరుగ్గా", "நன்றாக"],
  ["About the same", "पहले जैसा", "అలాగే ఉంది", "அப்படியே"],
  ["Worse", "ज़्यादा ख़राब", "ఇంకా బాగాలేదు", "மோசமாக"],
  ["Change call time", "कॉल का समय बदलें", "కాల్ సమయం మార్చండి", "அழைப்பு நேரத்தை மாற்று"],
  ["Done", "हो गया", "పూర్తయింది", "முடிந்தது"],
  ["Free", "मुफ़्त", "ఉచితం", "இலவசம்"],
  ["Doctor's note:", "डॉक्टर का नोट:", "డాక్టర్ నోట్:", "டாக்டரின் குறிப்பு:"],
  ["We missed your follow-up call", "आपका फॉलो-अप कॉल छूट गया", "మీ ఫాలో-అప్ కాల్ తప్పిపోయింది", "உங்கள் தொடர் அழைப்பு தவறிவிட்டது"],
  ["Get a doctor now", "अभी डॉक्टर बुलाएँ", "ఇప్పుడే డాక్టర్‌ను పిలవండి", "இப்போதே டாக்டரை அழையுங்கள்"],
  // records
  ["Visit notes, vitals, prescriptions and lab reports in one place.", "विज़िट नोट्स, वाइटल्स, पर्चे और लैब रिपोर्ट एक जगह।", "విజిట్ నోట్స్, వైటల్స్, ప్రిస్క్రిప్షన్‌లు, ల్యాబ్ రిపోర్టులు ఒకే చోట.", "வருகைக் குறிப்புகள், உயிர்க்குறிகள், மருந்துச் சீட்டுகள், ஆய்வக அறிக்கைகள் ஒரே இடத்தில்."],
  ["Latest vitals", "ताज़ा वाइटल्स", "తాజా వైటల్స్", "சமீபத்திய உயிர்க்குறிகள்"],
  ["Blood pressure", "बीपी", "బీపీ", "இரத்த அழுத்தம்"],
  ["Pulse", "नब्ज़", "నాడి", "நாடி"],
  ["Temperature", "तापमान", "ఉష్ణోగ్రత", "வெப்பநிலை"],
  ["Weight", "वज़न", "బరువు", "எடை"],
  ["Top number", "ऊपर वाला", "పై సంఖ్య", "மேல் எண்"],
  ["Bottom number", "नीचे वाला", "కింది సంఖ్య", "கீழ் எண்"],
  ["Usual range", "सामान्य सीमा", "సాధారణ పరిధి", "வழக்கமான வரம்பு"],
  ["Print", "प्रिंट", "ప్రింట్", "அச்சிடு"],
  ["No records yet", "अभी कोई रिकॉर्ड नहीं", "ఇంకా రికార్డులు లేవు", "இன்னும் பதிவுகள் இல்லை"],
  ["Lab reports", "लैब रिपोर्ट", "ల్యాబ్ రిపోర్టులు", "ஆய்வக அறிக்கைகள்"],
  ["Doctor visits", "डॉक्टर विज़िट", "డాక్టర్ విజిట్‌లు", "டாக்டர் வருகைகள்"],
  ["Physio", "फिज़ियो", "ఫిజియో", "பிசியோ"],
  ["Follow-up calls", "फॉलो-अप कॉल", "ఫాలో-అప్ కాల్‌లు", "தொடர் அழைப்புகள்"],
  // voice booking
  ["Tap the mic and say what's wrong", "माइक दबाकर बताइए क्या तकलीफ़ है", "మైక్ నొక్కి మీ సమస్య చెప్పండి", "மைக்கைத் தட்டி பிரச்சனையைச் சொல்லுங்கள்"],
  ["Listening…", "सुन रहे हैं…", "వింటున్నాం…", "கேட்கிறோம்…"],
  ["Tap to speak", "बोलने के लिए दबाएँ", "మాట్లాడటానికి నొక్కండి", "பேச தட்டுங்கள்"],
  ["Or type it here", "या यहाँ लिखें", "లేదా ఇక్కడ టైప్ చేయండి", "அல்லது இங்கே எழுதுங்கள்"],
  ["Go", "आगे", "ముందుకు", "தொடர்"],
  ["We heard:", "हमने सुना:", "మేము విన్నది:", "நாங்கள் கேட்டது:"],
  ["Confirm and book", "पक्का करें और बुक करें", "నిర్ధారించి బుక్ చేయండి", "உறுதிசெய்து புக் செய்"],
  ["Try again", "फिर से कोशिश करें", "మళ్ళీ ప్రయత్నించండి", "மீண்டும் முயலுங்கள்"],
  ["Send a doctor now", "अभी डॉक्टर भेजें", "ఇప్పుడే డాక్టర్‌ను పంపండి", "இப்போதே டாக்டரை அனுப்பு"],
  ["Call 112", "112 पर कॉल करें", "112కి కాల్ చేయండి", "112-ஐ அழையுங்கள்"],
  ["This sounds like an emergency. Call 112 now.", "यह आपातकाल लगता है। अभी 112 पर कॉल करें।", "ఇది అత్యవసరంలా ఉంది. వెంటనే 112కి కాల్ చేయండి.", "இது அவசரநிலை போல் தெரிகிறது. உடனே 112-ஐ அழையுங்கள்."],
  ["Sorry, we didn't catch that. Please try again, or pick a reason below.", "माफ़ कीजिए, समझ नहीं आया। फिर से बोलें या नीचे कारण चुनें।", "క్షమించండి, అర్థం కాలేదు. మళ్ళీ చెప్పండి లేదా కింద కారణం ఎంచుకోండి.", "மன்னிக்கவும், புரியவில்லை. மீண்டும் சொல்லுங்கள் அல்லது கீழே காரணத்தைத் தேர்ந்தெடுங்கள்."],
  ["Voice input isn't available in this browser. Type below instead.", "इस ब्राउज़र में बोलकर लिखना उपलब्ध नहीं है। नीचे लिखें।", "ఈ బ్రౌజర్‌లో వాయిస్ పని చేయదు. కింద టైప్ చేయండి.", "இந்த உலாவியில் குரல் வசதி இல்லை. கீழே எழுதுங்கள்."],
  ["A doctor now", "अभी एक डॉक्टर", "ఇప్పుడే డాక్టర్", "இப்போதே ஒரு டாக்டர்"],
  ["today", "आज", "ఈరోజు", "இன்று"],
  ["tomorrow", "कल", "రేపు", "நாளை"],
  ["morning", "सुबह", "ఉదయం", "காலை"],
  ["afternoon", "दोपहर", "మధ్యాహ్నం", "மதியம்"],
  ["evening", "शाम", "సాయంత్రం", "மாலை"],
  ["Shall we book it?", "क्या हम बुक करें?", "బుక్ చేయమంటారా?", "புக் செய்யலாமா?"],
];
const IDX = { hi: 1, te: 2, ta: 3 };
const DICT = new Map(PHRASES.map((r) => [r[0], r]));
const GREET = { "Good morning": ["सुप्रभात", "శుభోదయం", "காலை வணக்கம்"], "Good afternoon": ["नमस्ते", "నమస్కారం", "மதிய வணக்கம்"], "Good evening": ["शुभ संध्या", "శుభ సాయంత్రం", "மாலை வணக்கம்"] };

/* Translate one English phrase (used by voice prompts and anything built in code). */
function T(s) {
  if (LANG === "en") return s;
  const r = DICT.get(s);
  return r ? r[IDX[LANG]] : s;
}
function translateText(s) {
  if (LANG === "en") return s;
  const t = s.trim();
  if (!t) return s;
  const r = DICT.get(t);
  if (r) return s.replace(t, r[IDX[LANG]]);
  const g = /^(Good (?:morning|afternoon|evening)),\s*(.+)$/.exec(t);
  if (g) return s.replace(t, `${GREET[g[1]][IDX[LANG] - 1]}, ${g[2]}`);
  return s;
}

const ORIG = new WeakMap();          // text node -> its English text
const ORIG_ATTR = new WeakMap();     // element -> {attr: English}
const ATTRS = ["placeholder", "aria-label", "title"];
const SKIP = new Set(["SCRIPT", "STYLE", "TEXTAREA", "CODE"]);
let applying = false;

function translateNode(root) {
  if (!root) return;
  if (root.nodeType === 3) return translateTextNode(root);
  if (root.nodeType !== 1 || SKIP.has(root.tagName) || root.closest?.("[data-no-i18n]")) return;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT, {
    acceptNode: (n) => (n.nodeType === 1 && (SKIP.has(n.tagName) || n.hasAttribute("data-no-i18n")) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  });
  for (let n = root; n; n = walker.nextNode()) {
    if (n.nodeType === 3) translateTextNode(n);
    else if (n.nodeType === 1) translateAttrs(n);
  }
}
function translateTextNode(n) {
  if (n.parentElement && (SKIP.has(n.parentElement.tagName) || n.parentElement.closest("[data-no-i18n]"))) return;
  const known = ORIG.get(n);
  // A screen may have changed the text since we translated it: then that is the new English.
  const english = known && n.nodeValue === known.out ? known.en : n.nodeValue;
  const out = translateText(english);
  if (out !== n.nodeValue) n.nodeValue = out;
  ORIG.set(n, { en: english, out });
}
function translateAttrs(el) {
  for (const a of ATTRS) {
    if (!el.hasAttribute(a)) continue;
    const saved = ORIG_ATTR.get(el) || {};
    const cur = el.getAttribute(a);
    const english = saved[a] && cur === saved[a].out ? saved[a].en : cur;
    const out = translateText(english);
    if (out !== cur) el.setAttribute(a, out);
    saved[a] = { en: english, out };
    ORIG_ATTR.set(el, saved);
  }
}
function applyLang() {
  applying = true;
  document.documentElement.lang = LANG === "en" ? "en-IN" : `${LANG}-IN`;
  document.body.dataset.lang = LANG;
  translateNode(document.body);
  $$(".lang-pick").forEach((s) => (s.value = LANG));
  applying = false;
}
function setLang(l) {
  LANG = l;
  try { localStorage.setItem(LANG_KEY, l); } catch {}
  applyLang();
}

new MutationObserver((muts) => {
  if (applying || LANG === "en") return;
  applying = true;
  for (const m of muts) {
    if (m.type === "characterData") translateTextNode(m.target);
    else m.addedNodes.forEach(translateNode);
  }
  applying = false;
}).observe(document.body, { childList: true, subtree: true, characterData: true });

/* The picker: in the top bar (phone), the sidebar account card (desktop) and on the sign-in screen. */
function langPicker(cls = "") {
  return `<label class="lang-wrap ${cls}" data-no-i18n title="Language / भाषा / భాష / மொழி">${ic("globe")}<select class="lang-pick" aria-label="Language">
    ${LANGS.map(([k, name, short]) => `<option value="${k}" ${k === LANG ? "selected" : ""}>${cls === "top" ? short : name}</option>`).join("")}</select></label>`;
}
function mountPickers() {
  const top = $(".topbar .sign-out");
  if (top && !$(".topbar .lang-wrap")) top.insertAdjacentHTML("beforebegin", langPicker("top"));
  const side = $(".account-card label[for='account']");
  if (side && !$(".account-card .lang-wrap")) side.insertAdjacentHTML("beforebegin", langPicker("side"));
  const login = $("#login");
  if (login && !$(".lang-wrap.login-lang")) login.insertAdjacentHTML("beforebegin", langPicker("login-lang"));
  $$(".lang-pick").forEach((s) => (s.onchange = () => setLang(s.value)));
}
mountPickers();
applyLang();
