// SPDX-License-Identifier: AGPL-3.0-only
// Copyright 2026 Jimmy Wesley

// The Clipper's own UI language (spec J.15): the person's setting, stored
// with the extension, defaulting to the browser's. chrome.i18n cannot do
// this — it is locked to the browser locale — so every popup/editor/
// notification string lives HERE, and _locales keeps only what the
// platform itself reads (the manifest's name and description).
//
// The three dictionaries MUST stay key-identical. The README carries a
// one-line node check; a key present in one language and missing in
// another falls back to English at runtime rather than throwing, but the
// check is what keeps that fallback theoretical.

export const LANG_KEY = 'mkc:lang';
export const LANGS = ['auto', 'en', 'pt', 'es'];

// Self-named, deliberately not translated: a Portuguese speaker lost in an
// English UI must still recognise their own language in the selector.
export const LANG_NAMES = {
  auto: null, // rendered via the langAuto key, which IS translated
  en: 'English',
  pt: 'Português',
  es: 'Español',
};

export const MESSAGES = {
  en: {
    appName: 'MonkeyLLM Clipper',

    menuClipPage: 'Clip page',
    menuClipSelection: 'Clip selection',
    menuCaptureRegion: 'Capture region',
    menuClipImage: 'Send image',

    loginLead: 'Pair this browser with your Station.',
    originLabel: 'Server',
    originPlaceholder: 'https://station.example.com',
    tabPassword: 'Username & password',
    tabToken: 'Paste a token',
    usernameLabel: 'Username',
    passwordLabel: 'Password',
    tokenLabel: 'API key',
    tokenPlaceholder: 'mk_…',
    signIn: 'Pair',
    saveToken: 'Save token',
    pairHint: 'Pairing mints a clip-only key (read + ingest) on the server. Your password is used once and never stored.',
    tokenHint: 'Paste a key you already hold. It is checked against the server before it is saved.',

    errBadOrigin: 'That does not look like a server address. Use the full origin, like https://station.example.com.',
    errUnauthorized: 'The server did not accept that. Check the username and password.',
    errTokenBad: 'The server did not recognise that key.',
    errRateLimited: 'Too many attempts. Wait a minute, then try again.',
    errNetwork: 'Could not reach the server. Check the address and that the Station is running.',
    errPermission: 'The browser permission for that server was declined, so the Clipper cannot talk to it.',
    errNoIngest: 'You are paired, but no forest grants you ingest — you can look, not clip. Ask an administrator for an ingest grant.',
    errNoForest: 'Pick a forest first.',
    errNoSelection: 'Select something on the page first.',
    errUnclippable: 'This page cannot be clipped — the browser does not let extensions read it.',
    errNoImage: 'Could not read that image.',
    errRegionCancelled: 'Region capture cancelled.',
    errRegionExpired: 'The region wait expired before the selection arrived — try again.',
    regionComment: 'Note for the Gardener (optional)',
    regionCapture: 'Capture',
    regionCancel: 'Cancel',
    regionAdjust: 'Drag the box or its handles to adjust — Esc cancels',
    regionArrow: 'Arrow',
    regionRect: 'Box',
    regionPen: 'Pen',
    regionText: 'Text',
    regionListening: 'Listening — click to stop',
    sttPreparing: 'Starting the microphone…',
    sttProcessing: 'Processing…',
    askListening: 'Recording $1 — click to stop',
    regionUndo: 'Undo',
    regionMic: 'Dictate the note',
    regionMicStop: 'Stop dictating',
    regionMicDenied: 'Allow the microphone once in the tab that just opened, then try again.',
    askPlaceholder: 'Ask this forest…',
    askGo: 'Ask',
    linkSiteTitle: 'monkeyllm.com',
    linkGithubTitle: 'Repository on GitHub',
    permBody: 'The Clipper needs your microphone once, to dictate notes. The permission belongs to the extension — never to the pages you clip.',
    permOk: 'Done — you can dictate now. This tab closes itself.',
    permDenied: 'The microphone was refused. Allow it for this extension in the browser settings and try again.',
    errFileTooBig: 'That file is over 24 MB — too large to send from the extension.',
    errNeedTitleText: 'A note needs a title and some text.',

    forestLabel: 'Forest',
    forestNoIngest: 'no ingest grant — clipping is disabled here',
    destLabel: 'Branch',
    destPlaceholder: 'where clips land (optional)',

    btnClipPage: 'Clip page',
    btnClipSelection: 'Clip selection',
    btnScreenshot: 'Screenshot',
    btnClipBoth: 'Page + screenshot',
    btnRegion: 'Capture region',
    btnWrite: 'Write',
    btnNote: 'Quick note',
    btnUpload: 'Upload a file',

    noteTitlePlaceholder: 'Title',
    noteTextPlaceholder: 'Write in Markdown…',
    send: 'Send',
    cancel: 'Cancel',

    statusIdle: 'Ready to clip.',
    statusWorking: 'Clipping…',
    statusPlanted: 'Planted $1',
    statusJob: 'Job $1 running…',
    statusQueued: 'Forest busy — queued, retrying.',
    statusFailed: 'Failed: $1',
    queuePending: '$1 waiting for the forest to unlock',

    openStudio: 'Open Studio',
    logout: 'Log out',
    logoutTip: 'Discards the key from this browser only. To revoke it on the server, use Studio → People.',

    notifOkTitle: 'Clipped',
    notifFailTitle: 'Clip failed',
    notifUploadDone: 'Uploaded $1',
    notifPairFirst: 'Open the Clipper and pair with a server first.',
    notifPickForest: 'Open the Clipper and pick a forest first.',

    langLabel: 'Language',
    langAuto: 'Auto (browser)',

    editorPageTitle: 'MonkeyLLM — Write',
    editorPlaceholder: 'Write…',
    tbH2: 'Heading',
    tbBold: 'Bold',
    tbItalic: 'Italic',
    tbBullet: 'Bulleted list',
    tbOrdered: 'Numbered list',
    tbCode: 'Code block',
    tbQuote: 'Quote',
    dictate: 'Dictate',
    dictateStop: 'Stop dictation',
    draftSaved: 'Draft kept in this browser.',
    sentTitle: 'Sent',
    sentBody: 'The note is on its way — a notification will tell you when it is planted.',
    writeAnother: 'Write another',
  },

  pt: {
    appName: 'MonkeyLLM Clipper',

    menuClipPage: 'Recortar página',
    menuClipSelection: 'Recortar seleção',
    menuCaptureRegion: 'Capturar região',
    menuClipImage: 'Enviar imagem',

    loginLead: 'Emparelhe este navegador com a sua Station.',
    originLabel: 'Servidor',
    originPlaceholder: 'https://station.exemplo.com',
    tabPassword: 'Usuário e senha',
    tabToken: 'Colar um token',
    usernameLabel: 'Usuário',
    passwordLabel: 'Senha',
    tokenLabel: 'Chave de API',
    tokenPlaceholder: 'mk_…',
    signIn: 'Emparelhar',
    saveToken: 'Salvar token',
    pairHint: 'O emparelhamento cria no servidor uma chave só de recorte (leitura + ingestão). Sua senha é usada uma vez e nunca é armazenada.',
    tokenHint: 'Cole uma chave que você já possui. Ela é verificada no servidor antes de ser salva.',

    errBadOrigin: 'Isso não parece um endereço de servidor. Use a origem completa, como https://station.exemplo.com.',
    errUnauthorized: 'O servidor não aceitou. Verifique o usuário e a senha.',
    errTokenBad: 'O servidor não reconheceu essa chave.',
    errRateLimited: 'Tentativas demais. Aguarde um minuto e tente de novo.',
    errNetwork: 'Não foi possível alcançar o servidor. Verifique o endereço e se a Station está no ar.',
    errPermission: 'A permissão do navegador para esse servidor foi recusada, então o Clipper não consegue falar com ele.',
    errNoIngest: 'Você está emparelhado, mas nenhuma floresta concede ingestão — dá para olhar, não para recortar. Peça a um administrador uma concessão de ingest.',
    errNoForest: 'Escolha uma floresta primeiro.',
    errNoSelection: 'Selecione algo na página primeiro.',
    errUnclippable: 'Esta página não pode ser recortada — o navegador não deixa extensões lerem esse conteúdo.',
    errNoImage: 'Não foi possível ler essa imagem.',
    errRegionCancelled: 'Captura de região cancelada.',
    errRegionExpired: 'O tempo de espera da região expirou antes da seleção chegar — tente de novo.',
    regionComment: 'Nota para o jardineiro (opcional)',
    regionCapture: 'Capturar',
    regionCancel: 'Cancelar',
    regionAdjust: 'Arraste a caixa ou as alças para ajustar — Esc cancela',
    regionArrow: 'Seta',
    regionRect: 'Caixa',
    regionPen: 'Caneta',
    regionText: 'Texto',
    regionListening: 'Ouvindo — clique para parar',
    sttPreparing: 'Iniciando o microfone…',
    sttProcessing: 'Processando…',
    askListening: 'Gravando $1 — clique para parar',
    regionUndo: 'Desfazer',
    regionMic: 'Ditar a nota',
    regionMicStop: 'Parar de ditar',
    regionMicDenied: 'Permita o microfone uma vez na aba que acabou de abrir e tente de novo.',
    askPlaceholder: 'Pergunte a esta floresta…',
    askGo: 'Perguntar',
    linkSiteTitle: 'monkeyllm.com',
    linkGithubTitle: 'Repositório no GitHub',
    permBody: 'O Clipper precisa do seu microfone uma vez, para ditar notas. A permissão pertence à extensão — nunca às páginas que você recorta.',
    permOk: 'Pronto — já dá para ditar. Esta aba se fecha sozinha.',
    permDenied: 'O microfone foi recusado. Permita-o para esta extensão nas configurações do navegador e tente de novo.',
    errFileTooBig: 'Esse arquivo passa de 24 MB — grande demais para enviar pela extensão.',
    errNeedTitleText: 'Uma nota precisa de um título e de algum texto.',

    forestLabel: 'Floresta',
    forestNoIngest: 'sem concessão de ingest — recorte desativado aqui',
    destLabel: 'Galho',
    destPlaceholder: 'onde os recortes caem (opcional)',

    btnClipPage: 'Recortar página',
    btnClipSelection: 'Recortar seleção',
    btnScreenshot: 'Captura de tela',
    btnClipBoth: 'Página + captura',
    btnRegion: 'Capturar região',
    btnWrite: 'Escrever',
    btnNote: 'Nota rápida',
    btnUpload: 'Enviar arquivo',

    noteTitlePlaceholder: 'Título',
    noteTextPlaceholder: 'Escreva em Markdown…',
    send: 'Enviar',
    cancel: 'Cancelar',

    statusIdle: 'Pronto para recortar.',
    statusWorking: 'Recortando…',
    statusPlanted: 'Plantado $1',
    statusJob: 'Job $1 em execução…',
    statusQueued: 'Floresta ocupada — na fila, tentando de novo.',
    statusFailed: 'Falhou: $1',
    queuePending: '$1 esperando a floresta destravar',

    openStudio: 'Abrir Studio',
    logout: 'Sair',
    logoutTip: 'Descarta a chave apenas deste navegador. Para revogá-la no servidor, use Studio → People.',

    notifOkTitle: 'Recortado',
    notifFailTitle: 'Recorte falhou',
    notifUploadDone: 'Enviado $1',
    notifPairFirst: 'Abra o Clipper e emparelhe com um servidor primeiro.',
    notifPickForest: 'Abra o Clipper e escolha uma floresta primeiro.',

    langLabel: 'Idioma',
    langAuto: 'Automático (navegador)',

    editorPageTitle: 'MonkeyLLM — Escrever',
    editorPlaceholder: 'Escreva…',
    tbH2: 'Título de seção',
    tbBold: 'Negrito',
    tbItalic: 'Itálico',
    tbBullet: 'Lista com marcadores',
    tbOrdered: 'Lista numerada',
    tbCode: 'Bloco de código',
    tbQuote: 'Citação',
    dictate: 'Ditar',
    dictateStop: 'Parar ditado',
    draftSaved: 'Rascunho guardado neste navegador.',
    sentTitle: 'Enviado',
    sentBody: 'A nota está a caminho — uma notificação avisa quando ela for plantada.',
    writeAnother: 'Escrever outra',
  },

  es: {
    appName: 'MonkeyLLM Clipper',

    menuClipPage: 'Recortar página',
    menuClipSelection: 'Recortar selección',
    menuCaptureRegion: 'Capturar región',
    menuClipImage: 'Enviar imagen',

    loginLead: 'Empareja este navegador con tu Station.',
    originLabel: 'Servidor',
    originPlaceholder: 'https://station.ejemplo.com',
    tabPassword: 'Usuario y contraseña',
    tabToken: 'Pegar un token',
    usernameLabel: 'Usuario',
    passwordLabel: 'Contraseña',
    tokenLabel: 'Clave de API',
    tokenPlaceholder: 'mk_…',
    signIn: 'Emparejar',
    saveToken: 'Guardar token',
    pairHint: 'El emparejamiento crea en el servidor una clave solo de recorte (lectura + ingesta). Tu contraseña se usa una vez y nunca se almacena.',
    tokenHint: 'Pega una clave que ya tengas. Se comprueba contra el servidor antes de guardarse.',

    errBadOrigin: 'Eso no parece una dirección de servidor. Usa el origen completo, como https://station.ejemplo.com.',
    errUnauthorized: 'El servidor no lo aceptó. Revisa el usuario y la contraseña.',
    errTokenBad: 'El servidor no reconoció esa clave.',
    errRateLimited: 'Demasiados intentos. Espera un minuto y vuelve a intentarlo.',
    errNetwork: 'No se pudo alcanzar el servidor. Revisa la dirección y que la Station esté en marcha.',
    errPermission: 'El permiso del navegador para ese servidor fue rechazado, así que el Clipper no puede hablar con él.',
    errNoIngest: 'Estás emparejado, pero ningún bosque te concede ingesta — puedes mirar, no recortar. Pide a un administrador una concesión de ingest.',
    errNoForest: 'Elige un bosque primero.',
    errNoSelection: 'Selecciona algo en la página primero.',
    errUnclippable: 'Esta página no se puede recortar — el navegador no deja que las extensiones la lean.',
    errNoImage: 'No se pudo leer esa imagen.',
    errRegionCancelled: 'Captura de región cancelada.',
    errRegionExpired: 'La espera de la región expiró antes de que llegara la selección — inténtalo de nuevo.',
    regionComment: 'Nota para el jardinero (opcional)',
    regionCapture: 'Capturar',
    regionCancel: 'Cancelar',
    regionAdjust: 'Arrastra la caja o sus asas para ajustar — Esc cancela',
    regionArrow: 'Flecha',
    regionRect: 'Caja',
    regionPen: 'Lápiz',
    regionText: 'Texto',
    regionListening: 'Escuchando — haz clic para parar',
    sttPreparing: 'Iniciando el micrófono…',
    sttProcessing: 'Procesando…',
    askListening: 'Grabando $1 — haz clic para parar',
    regionUndo: 'Deshacer',
    regionMic: 'Dictar la nota',
    regionMicStop: 'Dejar de dictar',
    regionMicDenied: 'Permite el micrófono una vez en la pestaña que se acaba de abrir e inténtalo de nuevo.',
    askPlaceholder: 'Pregunta a este bosque…',
    askGo: 'Preguntar',
    linkSiteTitle: 'monkeyllm.com',
    linkGithubTitle: 'Repositorio en GitHub',
    permBody: 'El Clipper necesita tu micrófono una vez, para dictar notas. El permiso pertenece a la extensión — nunca a las páginas que recortas.',
    permOk: 'Listo — ya puedes dictar. Esta pestaña se cierra sola.',
    permDenied: 'El micrófono fue rechazado. Permítelo para esta extensión en la configuración del navegador e inténtalo de nuevo.',
    errFileTooBig: 'Ese archivo supera los 24 MB — demasiado grande para enviarlo desde la extensión.',
    errNeedTitleText: 'Una nota necesita un título y algo de texto.',

    forestLabel: 'Bosque',
    forestNoIngest: 'sin concesión de ingest — el recorte está desactivado aquí',
    destLabel: 'Rama',
    destPlaceholder: 'donde caen los recortes (opcional)',

    btnClipPage: 'Recortar página',
    btnClipSelection: 'Recortar selección',
    btnScreenshot: 'Captura de pantalla',
    btnClipBoth: 'Página + captura',
    btnRegion: 'Capturar región',
    btnWrite: 'Escribir',
    btnNote: 'Nota rápida',
    btnUpload: 'Subir un archivo',

    noteTitlePlaceholder: 'Título',
    noteTextPlaceholder: 'Escribe en Markdown…',
    send: 'Enviar',
    cancel: 'Cancelar',

    statusIdle: 'Listo para recortar.',
    statusWorking: 'Recortando…',
    statusPlanted: 'Plantado $1',
    statusJob: 'Job $1 en ejecución…',
    statusQueued: 'Bosque ocupado — en cola, reintentando.',
    statusFailed: 'Falló: $1',
    queuePending: '$1 esperando a que el bosque se desbloquee',

    openStudio: 'Abrir Studio',
    logout: 'Cerrar sesión',
    logoutTip: 'Descarta la clave solo de este navegador. Para revocarla en el servidor, usa Studio → People.',

    notifOkTitle: 'Recortado',
    notifFailTitle: 'El recorte falló',
    notifUploadDone: 'Subido $1',
    notifPairFirst: 'Abre el Clipper y empareja con un servidor primero.',
    notifPickForest: 'Abre el Clipper y elige un bosque primero.',

    langLabel: 'Idioma',
    langAuto: 'Automático (navegador)',

    editorPageTitle: 'MonkeyLLM — Escribir',
    editorPlaceholder: 'Escribe…',
    tbH2: 'Encabezado',
    tbBold: 'Negrita',
    tbItalic: 'Cursiva',
    tbBullet: 'Lista con viñetas',
    tbOrdered: 'Lista numerada',
    tbCode: 'Bloque de código',
    tbQuote: 'Cita',
    dictate: 'Dictar',
    dictateStop: 'Detener dictado',
    draftSaved: 'Borrador guardado en este navegador.',
    sentTitle: 'Enviado',
    sentBody: 'La nota está en camino — una notificación avisará cuando esté plantada.',
    writeAnother: 'Escribir otra',
  },
};

/** 'auto' | unknown → whatever the browser says, mapped onto the three
 *  dictionaries; an explicit choice wins as typed. */
export function resolveLang(pref) {
  if (pref === 'en' || pref === 'pt' || pref === 'es') return pref;
  const nav = String(
    (typeof navigator !== 'undefined' && navigator.language) || 'en',
  ).toLowerCase();
  if (nav.startsWith('pt')) return 'pt';
  if (nav.startsWith('es')) return 'es';
  return 'en';
}

/** The stored preference: 'auto' | 'en' | 'pt' | 'es'. */
export async function storedPref() {
  const got = await chrome.storage.local.get(LANG_KEY);
  const pref = got[LANG_KEY];
  return LANGS.includes(pref) ? pref : 'auto';
}

export async function setPref(pref) {
  await chrome.storage.local.set({ [LANG_KEY]: LANGS.includes(pref) ? pref : 'auto' });
}

/** The dictionary to render right now. Async because the preference lives
 *  in storage — which is exactly what lets the service worker read it
 *  before formatting a notification (J.15). */
export async function activeLang() {
  return resolveLang(await storedPref());
}

/** Translate. Substitutions are positional: '$1', '$2', … — same shape the
 *  _locales files used, so the strings moved over verbatim. */
export function t(lang, key, subs) {
  const table = MESSAGES[lang] || MESSAGES.en;
  let msg = table[key];
  if (msg === undefined) msg = MESSAGES.en[key];
  if (msg === undefined) return key;
  for (let i = 0; i < (subs || []).length; i++) {
    msg = msg.split('$' + (i + 1)).join(String(subs[i]));
  }
  return msg;
}

/** The BCP-47 tag for the browser's speech recognition: an explicit UI
 *  language picks its major variant; 'auto' trusts the browser wholesale,
 *  accent included. */
export function speechLang(pref) {
  const map = { pt: 'pt-BR', es: 'es-ES', en: 'en-US' };
  if (map[pref]) return map[pref];
  return (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
}
