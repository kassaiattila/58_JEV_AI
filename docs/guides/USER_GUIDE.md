# User guide

**Valid from:** 2026-10-01 (v1.5.0). **Audience:** people who use the interface.

## Plain-language summary

The interface runs in your browser and connects to a local service running on your own computer. There is no login: every change is recorded under the name chosen in the **Who is working?** (*Ki dolgozik?*) field in the header. The unit of work is the work package: the documents in a folder, a list of files you specify, or the emails from a mailbox. You work on a package in three stages: in **Processing** (*Feldolgozás*) you check the processing settings and start a run (the system recognises each document's type itself); in **Review** (*Ellenőrzés*) you resolve the to-dos and correct wrong data next to an image of the document; in **Result** (*Eredmény*) you download the tables and approve the live run. A paid AI call is always started by a person, after confirmation, with the cost budget shown in advance.

## 1. A few terms first

The interface starts in Hungarian; the **HU / EN** buttons in the header switch it to English (section 2.2). This guide quotes the English labels, and on first mention gives the Hungarian label in italics, for example **Who is working?** (*Ki dolgozik?*). The full vocabulary is in the [glossary](../GLOSSARY.md). For this guide, these terms are enough:

| Term | Meaning |
|---|---|
| Work package (*munkacsomag*) | Documents or emails from one source, handled together. It has one set of processing settings and can have several runs. |
| Processing settings (*feldolgozási beállítások*) | The recipe and processing path, Azure recognition, reuse of earlier answers and, for emails, task proposals. The recipe determines supported files; PDF documents use type recognition, while Word, Excel, TXT and CSV use source-bound fact extraction. |
| Run (*futás*) | Processing the package's items once. It is either a **trial run** (it can be viewed and downloaded but not released) or a **live run** (valid once approved). |
| To-do (*teendő*) | A reason on an item that needs a person to check it, for example ‘Uncertain value: Gross amount (probability 0.58)’ (*Bizonytalan érték: Bruttó összeg (valószínűség 0,58)*). Each reason is resolved separately. |
| Worker (*feldolgozó*) | The background program that processes the items of runs one by one. If it is not running, runs wait. |
| Local service (*helyi szolgáltatás*) | The program that serves the interface and accepts requests only from this computer. |
| JEV and GPT | The two paid AI services. JEV gives probabilities for closed questions (which value is the right one, whether a statement is true); GPT (OpenAI's text-generation model) reads data out of text. |

## 2. Starting up and the parts of the screen

1. The start script launches the local service and the worker in the background (the exact command is in the Technical details). You only need to start it once: closing the browser or the tab does not stop it, and does not interrupt work in progress either.
2. Open http://127.0.0.1:8930/ in your browser. The address works only on this computer.
3. The sidebar on the left has two main parts: **Work packages** (*Munkacsomagok*) for daily work, and **Settings** (*Beállítások*).
4. On the left of the header is the worker badge: ‘Worker running’ (*Feldolgozó fut*) or ‘Worker not running’ (*Feldolgozó nem fut*), followed by ‘N items waiting’ (*N tétel vár*) when work is queued. A red ‘The local service is not reachable’ (*A helyi szolgáltatás nem érhető el*) badge means the service has stopped (see section 11). Next to it are the **HU / EN** language buttons.
5. On the right of the header is the **Who is working?** field.

### 2.1 Who is working?

- Every action that changes something is recorded under the selected name: creating and managing a package, processing settings, starting and stopping a run, corrections, resolving to-dos, approval, task-proposal decisions, mailbox downloads and **Back up now** (*Mentés most*). This way you can always see later who did what. Without a name, the service rejects these actions (‘enter your name in the “Who is working?” field at the top…’ (*add meg a neved fent a „Ki dolgozik?” mezőben…*)).
- If the list under Settings › Users (*Felhasználók*) is not empty, the field works as a picker (‘Choose your name’ (*Válaszd ki a neved*)). Until a name is selected, ‘Select your name before making changes.’ (*Módosítás előtt válaszd ki a neved.*) is shown. Only a name on the list is accepted.
- If the list is empty, you can type any name. After **Save** (*Mentés*), ‘Remembered’ (*Megjegyezve*) appears; the **Add users** (*Felhasználók felvétele*) link takes you to the name list.
- The name is remembered in this browser and applies to every open tab. If you change it in one tab, the other tabs show the new name too.
- The name is not a permission and has no password behind it: anyone can choose any name.
- Once a name is selected, a **My work today** (*Mai munkám*) link appears next to the field (section 9).

### 2.2 Language

The **HU / EN** buttons switch only the interface labels. Document data, names and file names do not change, and unsaved corrections are kept. The choice is remembered in this browser. You can set the same on the Settings › Language (*Nyelv*) page.

## 3. The work package list

The **Work packages** page starts with the **New work package** (*Új munkacsomag*) button, with the table of packages below it. By default the newest package comes first. The columns are: ‘Name’ (*Név*), ‘Next step’ (*Következő lépés*), ‘Last run’ (*Utolsó futás*), ‘Item’ (*Tétel*), ‘Open to-dos’ (*Nyitott teendő*), ‘Source’ (*Forrás*), ‘Processing’ (*Feldolgozás*), ‘Assignee’ (*Felelős*), ‘Last activity’ (*Utolsó tevékenység*) and ‘Created’ (*Létrehozva*). ‘Next step’ (for example ‘Start trial run’ (*Próbafutás indítása*), ‘Review: 3 to-dos’ (*Ellenőrzés: 3 teendő*) or ‘Approval’ (*Jóváhagyás*)) takes you to the matching stage of the package. ‘Open to-dos’ counts the to-dos of the latest run and takes you to Review. The list refreshes itself.

Tables work the same way in every list:

- **Search:** the ‘Search all columns…’ (*Keresés az összes oszlopban…*) field ignores both letter case and accents (‘szamla’ finds ‘Számla’, Hungarian for ‘invoice’).
- **Sorting:** click a column header (ascending, descending, off). Shift + click adds a further sort level.
- **Filtering:** use the funnel icon in the column header. Text columns offer ‘Contains’ (*Tartalmazza*), number and date columns ‘At least’ (*Legalább*) / ‘At most’ (*Legfeljebb*), and columns with a fixed set of values offer checkboxes; everywhere you can also choose ‘all / empty only / filled only’ (*mind / csak üres / csak kitöltött*). Active filters appear as tags above the table. Remove them one by one with ×, or all at once with **Clear all filters** (*Minden szűrő törlése*).
- **Only my work packages** (*Csak a saját csomagjaim*): shows only the packages you are the owner of. You need to choose a name first.
- **Hidden packages too** (*Elrejtett csomagok is*): also shows hidden packages, with a ‘Package’ (*Csomag*) column showing their state.
- **Columns (x/y)** (*Oszlopok (x/y)*): turn on hidden columns here, for example ‘Open to-dos incl. earlier runs’ (*Nyitott teendő a korábbi futásokkal*) or ‘Source location’ (*Forrás helye*). **Reset** (*Alaphelyzet*) restores the original columns. The choice is remembered per table in this browser.
- **Paging:** at the bottom you find ‘1–100 of N rows’ (*1–100 / N sor*), the number of rows per page (50, 100, 250, 500) and the page buttons.

### 3.1 Download

Every table has a **Download** (*Letöltés*) button in its top-right corner. The panel lets you choose:

- **Format:** Excel (one worksheet, numbers stored as numbers), CSV (semicolon-separated, so Hungarian Excel splits it into columns) or JSON (for machine processing).
- **Rows:** ‘All rows’ (*Minden sor*), ‘Filtered rows’ (*A szűrt sorok*) or ‘Selected rows’ (*A kijelölt sorok*). You can only select rows in tables that have a checkbox on each row (for example the tables in Result). By default the narrowest scope is chosen: the selection; failing that, the filter; otherwise all rows.
- **Columns:** only the visible columns, or all columns including the hidden ones.

Before you download, the panel shows the number of rows and columns; the row order matches the table. The file goes to your browser's downloads. Text that looks like a formula does not turn into a formula in the file.

## 4. New work package

The **New work package** button offers three sources:

- **Documents from a folder** (*Egy mappa dokumentumai*): fill in ‘Full folder path’ (*Mappa teljes útvonala*), or click **Browse…** (*Tallózás…*) and choose the folder in the Windows folder picker. The package gets the supported documents directly in the folder, in path order: PDF, DOCX, XLSX, UTF-8 TXT and CSV. Tick **Include subfolders** (*Almappák is*, off by default) to include supported documents in subfolders too. The output folder of the named copies (section 10.2) is left out, so earlier copies do not return as new documents. A document in a subfolder is shown with its relative path (for example `2026-09/invoice.pdf`). ‘Name’ is optional; if empty, the folder name is used.
- **Specific files** (*Megadott fájlok*): in ‘Full file paths, one per line’ (*Fájlok teljes útvonala, soronként egy*) you can list files from several folders. **Browse…** opens the Windows file picker, where you can choose several files at once. The chosen files are added after the lines already in the field, each only once. Here the name is required.

**Browse…** asks the local service to open the Windows picker on this computer. While the picker is open, the button reads ‘The picker is open…’ (*A választó ablak nyitva…*). If you cannot see the picker, check the taskbar: it may have opened behind the browser. Cancelling changes nothing. A path can always be typed instead. Only one picker can be open at a time, and one left open for ten minutes is closed.
- **From a mailbox** (*Postafiókból*): the mailbox form (section 10.1), with the **Download now: new work package** (*Letöltés most: új munkacsomag*) button. The worker does the download; the new emails become a package, which appears in the list.

After **Create** (*Létrehozás*), the package's Processing stage opens, and the person who created it becomes the package's owner. The files stay where they are and are never changed. As a document is added, the system keeps an unchanging copy of it (its source instance), and from then on the package works from that copy: processing, the page image in review and the named copies. So if the original file is later edited, moved or deleted, you still see exactly what the result was made from. You cannot add new documents to an existing package from the interface: new documents need a new package (a work folder can extend its own package by itself).

## 5. The work package page

The header shows the package name and a summary (how many documents or emails, when the last run was). Next to it:

- **Assignee:** the package's owner (the person from the Users list assigned to it), or ‘no owner’ (*nincs felelős*). This is not a permission; other people can work on the package too. The **Only my work packages** filter is based on it.
- **The next-step button**, for example ‘Start trial run →’. If you are already on that stage's page, only the label ‘Next step: …’ (*Következő lépés: …*) is shown.
- **Manage package** (*Csomag kezelése*) (section 5.1).

Below this are the tabs of the three stages, each showing its own state: **1 Processing** (for example ‘ready to start’ (*indítható*), ‘cannot start’ (*nem indítható*), or the last run's mode, state and progress), **2 Review** (‘To-dos: N’ (*N teendő*) or ‘no to-dos’ (*nincs teendő*)), **3 Result** (‘none yet’ (*még nincs*), ‘trial result’ (*próba-eredmény*), ‘awaiting approval’ (*jóváhagyásra vár*), ‘released’ (*kiadva*)). By default a package opens at the stage where its next step is. You can bookmark the address in the browser's address bar: it takes you back to the same package and stage.

The possible next steps are: ‘Empty work package’ (*Üres csomag*), ‘Start trial run’, ‘Cannot start’ (*Nem indítható*), ‘Running: 3/10’ (*Fut: 3/10*), ‘Failed or stopped run: rerun’ (*Hibás vagy leállított futás: újrafuttatás*), ‘Review: N to-dos’, ‘Trial OK: live run’ (*Próba rendben: éles futás*), ‘Approval’ and ‘Released: download result’ (*Kiadva: eredmény letöltése*).

### 5.1 Manage package

- **Rename** (*Átnevezés*): enter a new name, then click **Save**.
- **Hide from the list** (*Elrejtés a listából*) / **Show in the list again** (*Visszahozás a listába*): a hidden package keeps its runs and results, can still be opened directly, and reappears in the list when you tick **Hidden packages too**. A watched folder does not add new documents to a hidden package; it starts a new package instead.
- **Delete permanently…** (*Végleges törlés…*): only possible on a package that has never had a run. It asks for confirmation (‘Delete this package permanently?’ (*Biztosan törlöd a csomagot?*)). The package and its item list are deleted; the files stay where they are. Deletion cannot be undone, and a record of it stays in the log. A package that has runs can only be hidden.

### 5.2 Original or unified names

The package's documents, the items of a run and the item list of Review can show each document under its original file name or under its **unified name** (*egységes név*): the content-based file name of the File names view (section 8), for example `2026-09-12_SZAMLA_Minta-Kft_SZ-2026-001234.pdf`. The **Name:** (*Név:*) switch above each of these lists chooses between **Original** (*Eredeti*) and **Unified** (*Egységes*). The choice applies to every list and is remembered for the person in **Who is working?** in this browser; the default is Unified.

- A document has a unified name only once a run has processed it. Until then its original name is shown, and its tooltip says ‘No unified name yet: the item has not been processed.’ (*Még nincs egységes név: a tétel még nem futott le.*). In the package's list, each document's name comes from the latest run that processed it.
- A ⚠ mark before a unified name means the name is uncertain: its copy would go into the review folder. Pointing at the mark shows why (for example a missing invoice number). Correcting that field in Review makes the name certain.
- With a unified name shown, the tooltip gives the original name. Searching, sorting and filtering work on the name that is shown; the search also finds the other name.
- Emails have no file name of their own and always keep their subject.
- The **Columns** menu offers **Unified name** (*Egységes név*), **Original name** (*Eredeti név*) and **Unified name status** (*Egységes név állapota*: ‘Done’, ‘To check’ (*Ellenőrzendő*), ‘Not yet’ (*Még nincs*), ‘None (email)’ (*Nincs (levél)*)), so both names can be seen side by side.

## 6. Processing

### 6.1 Processing settings

The package's processing recipe determines which documents it accepts. Choose **PDF and email processing** for PDF documents and downloaded emails. For DOCX, XLSX, UTF-8 TXT or CSV files, choose **Document processing — PDF, Word, Excel, TXT, CSV** and save the settings; this recipe also accepts PDFs in the same package.

Settings › Processing shows each recipe's own title, supported inputs and explanation. **Recipe version: 1** identifies the revision of that particular recipe; two recipes can have the same version number. The path descriptions also follow the selected recipe in the package settings. Word, Excel, TXT and CSV need GPT extraction, optionally checked by JEV; they cannot use the S path. Azure recognition applies only to PDF files. **Unknown PDFs** (*Ismeretlen PDF-ek*): when a PDF's recognised type has no fitting type pack (for example a declaration or a payment reminder), the default setting, general facts, still extracts source-bound facts with GPT and JEV, within the run's budget, and the document is reviewed like a Word or Excel file; the recognised type and its uncertainty to-do stay. With the other setting, a stop for manual review, such a PDF stops with a to-do, as before. A scanned PDF is read with local text recognition for this and always keeps a to-do saying that its reading is partial. The historical PDF path comparison does not measure extraction quality for the other formats.

Native documents use GPT to extract facts, with optional JEV support checking. The JEV-only S path is unavailable for these documents; an incompatible choice prevents the run from starting. Azure recognition applies to PDF files only. Reading gaps remain visible after review; checking an extracted value does not recover unread content.

- **A PDF document** (*PDF-irat*): the system first recognises its type (for example an invoice, a utility bill, a bank statement or a certificate), then extracts that type's fields on the chosen path and checks them in code (for example the tax number's check digit and the totals). A type that cannot be decided becomes a to-do.
- **An email** (*levél*): the system recognises its intent (the purpose of the email, for example that an invoice has arrived) and suggests the next step; its PDF attachments are processed as documents, traced back to the email; task proposals are made on request.

The **Processing settings** (*Feldolgozási beállítások*) card shows the settings and what each chosen value means. If nobody has saved settings for the package yet, the card says ‘Default settings: if you do not change them, they are saved to the package when a run starts.’ (*Alapbeállítás: ha nem módosítod, a futás indításakor ez mentődik a csomaghoz.*). The settings:

- **Processing path** (*Feldolgozási út*), the first setting: which tool does the work. It is one choice of four; every path is followed by the same checks in code.
  - ‘Automatic (recommended) — JEV and GPT’ (*Automatikus (ajánlott) — JEV és GPT*): JEV recognises each document's type and each email's intent, and the document type's recommended path runs: S on Hungarian and foreign invoices, G on utility bills (because of the line items) and on every other document type (those only have a G path).
  - ‘JEV where possible — cheaper, no line items; GPT elsewhere (S)’ (*JEV, ahol lehet — olcsóbb, tételsorok nélkül; máshol GPT (S)*): code collects the possible values and JEV chooses among them. Only the eight invoice types (Hungarian and foreign invoices, six utility bills) have this path. Every other document type has no JEV path, so with this choice it runs on the G path (GPT + JEV), so that its data is still read; the pre-start overview then gives an OpenAI budget and says how many documents it is for. To run with no OpenAI call at all, check that the overview's OpenAI line says it is not called.
  - ‘GPT + JEV — with line items (G)’ (*GPT + JEV — tételsorokkal (G)*): GPT reads the data including the line items, and JEV checks each field. It costs more.
  - ‘GPT only, without JEV (OpenAI)’ (*Csak GPT, JEV nélkül (OpenAI)*): the run uses OpenAI only (and Azure recognition, if that is on). Earlier GPT answers are reused as with JEV (see **Earlier answers** below).
    - GPT recognises each document's type, about 0.001–0.002 USD per document. If its confidence cannot be measured, or the call fails, the document gets a to-do instead of a guessed type.
    - Every document runs on the G path: GPT reads the data, and the code checks it. Every extracted value must be printed on the document, otherwise the to-do ‘The extracted value is not printed on the document’ (*A kinyert érték nem szerepel az iratban*) appears. The check-digit, amount and required-field checks stay.
    - Without JEV's second opinion more errors can pass without a flag. Measured on the golden set on 2026-10-02: GPT recognised the type of 99 of 102 documents (JEV all 102) and stated its 3 errors confidently too. One of them already gets a to-do, and since 2026-10-02 a check in code flags a type that presumes a Hungarian issuer when GPT itself says the issuer is not Hungarian (‘The type (…) presumes a Hungarian issuer…’ (*A típus (…) magyar kiállítót feltételez…*)); on the golden set this caught one of the other two, and flagged none of the 99 correct types. The remaining error (a Hungarian company's invoice in English, taken as foreign) can still pass without a to-do; 27 of the 1010 fields of the 70 golden documents differed from the checked value.
    - GPT also recognises each email's intent, with the same questions as JEV: on the 96-email golden set it got 94 right and sent its 2 errors to manual review; about 0.0025 USD per email, from a budget of at most 0.07 USD. Routing and the task proposal work as with JEV. If the confidence cannot be measured, or the call fails, the email gets a to-do (‘The confidence of the email's intent cannot be measured; check it by hand’ / ‘GPT intent recognition failed …’; *A levél-szándék bizonyossága nem mérhető; ellenőrizd kézzel* / *A GPT-s szándékfelismerés nem sikerült …*). Its PDF attachments run as documents.
    - The run gets no JEV budget at all, so no JEV call can happen; the pre-start overview says ‘JEV: not called (switched off)’ (*JEV: nem hívódik (kikapcsolva)*).
  - A package of emails only offers two choices, ‘With JEV (recommended)’ (*JEV-vel (ajánlott)*) and ‘GPT only, without JEV’, because the documents' path does not act on emails; their PDF attachments run as documents on the automatic path.
  - The saved settings keep the path and the use of JEV as two values, so packages and runs saved before this picker keep their meaning; an older package without the use of JEV ran with JEV.
  - What the measurements say (Settings › Processing shows the full comparison): on the header fields of the golden set the two paths agree with the checked values about equally often (S: 942 of 953 fields, G: 940 of 953; the G measurement is older), the S path costs about a third to a sixth as much per document, and only the G path reads line items.
- **Earlier answers** (*Korábbi válaszok*), for JEV and GPT alike (until 2026-10-02 ‘JEV answers’, for JEV only): with ‘earlier answer may be reused’ (*korábbi válasz újrahasználható*), the earlier answer to the same question comes back free and instantly, so a rerun costs nothing and gives the same result; this is recommended for everyday work. A question is the same when the model, the instructions and the document's text are all the same; if any of them changes, a new, live call goes out. A reused GPT answer is in the call log with cost 0 and the call it came from. ‘always a live call’ (*mindig élő hívás*) is for measurements, and the cost can grow up to the budget.
- **Azure recognition** (*Azure-felismerés*): ‘for weak scans’ (*gyenge szkennelésnél*) by default. If the local text recognition of a scanned document is weak, the system uses the more accurate, paid Azure recognition, from a budget of at most 0.02 USD per document; every call is in the call log. If the run's Azure budget runs out, the local text goes on and the document gets the to-do ‘Weak local recognition; Azure recognition was skipped because of the run's budget’ (*Gyenge helyi felismerés; az Azure-felismerés a futás kerete miatt elmaradt*). With ‘off’ (*kikapcsolva*) only the local recognition runs.
- **Task proposal** (*Feladatjavaslat*) (emails only): ‘off’ (*kikapcsolva*) by default. When it is switched on, GPT makes a proposal for each email, which adds a cost per email.
- **Cost budget** (*Költségkeret*): the maximum amount per item and per provider that the system reserves when the run starts. It is an upper limit; the actual cost is usually lower.

To change them, click **Change** (*Módosítás*): the card shows a picker for each setting with its meaning, the budget, ‘Note (optional)’ (*Megjegyzés (elhagyható)*) and the **Save settings** (*Beállítások mentése*) button. Every save creates a new version; earlier runs keep their own settings. If someone else changed the settings in the meantime, a message tells you so; your choices are kept, so just save again. If the processing itself has changed since the settings were saved, or the package still uses an earlier version of the processing (for example an invoice-only one with the type given in advance), a warning appears with a **Switch to the current processing** (*Átállítás a mostani feldolgozásra*) button: the settings are kept and a type given in advance is dropped, because the system recognises it. The **How the system works and what the settings mean** (*Hogyan dolgozik a rendszer, és mit jelentenek a beállítások*) link leads to Settings › Processing.

### 6.2 Readiness

Before you start, the **Run** (*Futtatás*) card shows anything that blocks the run. Blockers include: ‘The work package has no items.’ (*A munkacsomagban nincs tétel.*), ‘The processing does not handle: …’ (*A feldolgozás nem kezeli: …*), ‘Missing source: …’ (*Hiányzó forrás: …*) and ‘The source content changed since it was added: …’ (*A forrás tartalma a felvétel óta változott: …*); the last two only for documents added before the system kept copies. For the others, ‘The copy kept when it was added is missing or damaged: …’ (*A felvételkori példány hiányzik vagy sérült: …*) blocks, while a changed or deleted original is only a warning: ‘The original file has changed since it was added; the copy kept then is processed: …’ (*Az eredeti fájl a felvétel óta megváltozott; a felvételkori példány kerül feldolgozásra: …*). While there is a blocker, the start buttons are disabled. Below the buttons, ‘What happens when the run starts’ (*Mi történik indításkor*) lists each service the run may call, with its budget and what it is for, for example ‘JEV up to 0.26 USD: type recognition and data extraction of 3 document(s); …’, ‘OpenAI up to 0.31 USD: 1 document(s) on the G path; …’; a service that will not be called is named too (‘OpenAI: not called, every document runs on the S path.’ (*OpenAI: nem hívódik, minden irat az S-úton fut.*)). A document whose type has not been recognised yet counts with the more expensive G path, because the type decides the path.

### 6.3 Trial run, live run, rerun

- **Trial run…** (*Próbafutás…*): processing runs in full, with the same paid calls, but the result can only be viewed and downloaded, not released. Use it to try out new settings or a new document type.
- **Live run…** (*Éles futás…*): a person approves the result in the Result stage, once every item has finished and no to-dos are open. This is the valid result.
- **Rerun…** (*Újrafuttatás…*): repeats the latest run in the same mode, with the same input, as a new run. Useful after an error, a stop or a change of the settings.

The highlighted button is always the one the package's next step calls for. Only one run at a time can be in progress on a package.

### 6.4 The confirmation page

The three buttons do not start anything straight away; they take you to a summary page showing ‘Work package’ (*Munkacsomag*), ‘Items’ (*Tételek*), ‘Processing settings’ (with ‘default settings, saved to the package when the run starts’ (*alapbeállítás, az indításkor mentődik a csomaghoz*) if none were saved), ‘Maximum cost’ (*Legnagyobb költség*) per provider, with the note ‘involves paid calls…’ (*fizetős hívásokkal jár…*) or ‘involves no paid calls’ (*nem jár fizetős hívással*), and the ‘What happens when the run starts’ list (section 6.2). At this point the system fetches the budget afresh (‘Refreshing the cost limit…’ (*A költségkeret frissítése…*)), and starting is disabled until it has done so. You start with **Start trial run**, **Start live run** (*Éles futás indítása*) or **Start rerun** (*Újrafuttatás indítása*); **Cancel** (*Mégse*) takes you back. If the package or its settings changed in the meantime, the page tells you (‘…We refreshed it; review it and start again.’ (*…Frissítettük, nézd át és indítsd újra.*)). Once started, the run page opens.

### 6.5 The run page

- **Header:** the mode and time, the state (‘Queued’ (*Sorban áll*), ‘Running’ (*Fut*), ‘To-dos pending’ (*Teendő vár*), ‘Done’ (*Kész*), ‘Failed’ (*Hibás*) or ‘Stopped’ (*Leállítva*)), the processing settings, and who started the run.
- **Items:** for each item, its run state, the result and the number of to-dos. Clicking a to-do opens Review. The **Name:** switch shows the original or the unified names (section 5.2). Each item also shows its processing cost: one column per provider and model the run called successfully (for example ‘JEV (USD)’; the header names the model too, for example ‘JEV · jev-1.13.0 (USD)’, when a provider used several), and **Total cost (USD)** (*Költség összesen (USD)*). The **Columns** menu adds **From earlier answers (count)** (*Korábbi válaszból (db)*): how many of the item's questions were answered free from an earlier identical answer.
- **Cost** (*Költség*): first **Cost of the run** (*A futás költsége*), the run's actual cost over every provider. Below it, for each provider (JEV, OpenAI, Azure DI), the paid calls (how many failed), their actual cost and the models, then how many questions were answered free from earlier answers. A call whose cost is not known (for example a failed or interrupted attempt) is not counted as a cost; its reserved amount is shown apart as ‘Reserved, outcome unknown’ (*Lefoglalt, ismeretlen kimenetelű*), because the budget still counts it.
- **Planned and actual** (*Tervezett és tényleges*): for each provider, what the pre-start overview expected (‘expected’ (*várható*), ‘possible’ (*lehetséges*) or ‘not expected’ (*nem várt*)) against the actual cost. If a provider was called although the overview did not count on it, a warning says so. For a run started before the overview was saved with the run, only a note is shown.
- **Budget** (*Keret*), closed by default; its title gives each provider's share used (for example ‘Budget (JEV 13%, OpenAI 0%)’). Opened, it shows for each provider the committed amount against the budget: the cost of the completed calls plus the reserved upper bound of the calls not yet settled. It opens by itself when a budget is at least 80% used, or when the budget stopped something in the run (a to-do says so).
- **Job queue** (*Munkasor*): how many jobs are queued, running, done, failed (given up) or stopped.
- **Call log (raw model calls)** (*Hívásnapló (nyers modellhívások)*): an expandable list of the paid calls. It is empty if every answer came from the cache.
- **Stop** (*Leállítás*) (only while the run is in progress): needs two clicks (‘Sure? Click again’ (*Biztosan? Kattints újra*)). Queued items stop at once; the item in progress stops after its next step.
- **Result**, or for a live run **Result and approval** (*Eredmény és jóváhagyás*): takes you to the package's Result stage.

While a run is in progress, the Processing stage shows a progress bar, and below it the ‘Runs of the work package’ (*A csomag futásai*) table lists every run of the package, with the actual cost of each run (**Cost (USD)**). Below that, **Cost of the work package** (*A csomag költsége*) adds up every run of the package per provider and model: paid calls, questions answered from earlier answers, and cost, with the total above the table.

## 7. Review

Before a run, the Review stage only shows the package's documents (section 7.9). After a run, the workspace opens here.

### 7.1 The workspace

- **At the top:** the run picker (the latest run by default; you can type to search), the number of open to-dos, the ‘Run details’ (*A futás részletei*) link, the **Name:** switch (original or unified names in the item list, section 5.2) and the keyboard help.
- **On the left, the item list:** a search box (‘Search N items…’ (*Keresés N tétel között…*)) and a ‘to-dos only’ (*csak teendős*) checkbox. For each item you see the name (for an email, the subject), its state (‘to-do’ (*teendő*), ‘resolved’ (*rendezve*), ‘closed’ (*lezárva*), ‘not run yet’ (*még nem futott*), ‘Failed’…), and the ‘To-dos: N’, ‘N earlier to-dos’ (*N korábbi teendő*) and ‘unsaved’ (*mentetlen*) markers. The workspace opens at the first item that has a to-do.
- **In the middle** is the page image of the document (from the copy kept when it was added; if the original file has changed or disappeared since, a note above the image says so), and **on the right** are the to-dos and the fields. You can drag the divider between them (or use ← / → on the keyboard); the ratio is remembered.

### 7.2 To-dos

- A to-do about one field is shown **at that field**, in red under its value, one sentence per reason (for example ‘Uncertain value: Gross amount (probability 0.58)’). A failed check of one field stands there too and names the field (for example ‘The tax ID format is not recognised: Supplier tax ID’ (*Az adószám alakja nem ismerhető fel: Szállító adószáma*)); a check of the whole document (totals, line items, dates) stays at the top. You settle it with the field's ✓ (section 7.4).
- At the top of the right-hand panel are only the to-dos about the whole document (for example ‘The supplier and the buyer have the same tax ID’ (*A szállító és a vevő adószáma azonos*) or an uncertain document type). The **Resolved** (*Rendezve*) button closes that one reason, under your name; the other reasons stay open.
- **Saving with Save correction does not close a to-do**; the field's ✓ does (the exception is correcting an email's intent, section 7.8).
- **Earlier to-dos** are reasons left open on the same document by an older run; they do not block the approval of this run. One about a field is shown at that field, in grey, as ‘from an earlier run: …’ (*korábbi futásból: …*), or ‘from N earlier runs: …’ when several runs left the same one; the field's ✓ closes it too, because a person has now verified the value. The ones about the whole document are at the bottom of the panel, closed: **Earlier to-dos about the whole document (N) — they do not block this run** (*Korábbi, egész iratra szóló teendők (N) — ezt a futást nem akadályozzák*), each with **Resolved**.
- **Checks on the saved data** (*Ellenőrzések a mentett adaton*): rules written in code (for example, whether the line items add up to the total) that run again, without paid calls, after you save a correction. A ‘Row N’ (*N. sor*) button takes you to the failing row. A check marked ‘advisory only, not a to-do’ (*csak jelzés, nem teendő*) does not open a to-do.

### 7.3 Fields, colours, boxes

- **Filter** above the fields: **To fix** (*Javítandó*) shows the fields with an open to-do in this run, **Uncertain** (*Bizonytalan*) the fields whose estimate is ‘To check’ or ‘Likely wrong’ and that nobody has verified or corrected yet, **All** (*Mind*) every field; each button shows how many fields it has. An item opens on To fix when it has something to fix, otherwise on All; the filter you choose stays for the next item while that item has fields in it. When the last field of the filter is done, the panel says so (for example ‘Nothing is left to fix on this item.’ (*Ezen a tételen nincs több javítandó mező.*)), with a **Next item with to-dos** (*Következő teendős tétel*) button. The keys move between the filtered fields (section 7.7).
- **Previous item / Next item** (*Előző tétel / Következő tétel*) at the top of the panel move through the items without going back to the list on the left.
- For each field you see its name, an ‘unsaved’, ‘verified’ (*ellenőrizve*) or ‘corrected’ (*javítva*) marker, the model's estimate as a percentage, and a source marker. The colour of the estimate is its confidence band: green ‘Confident’ (*Magabiztos*), blue ‘To check’ (*Ellenőrzendő*), red ‘Likely wrong’ (*Valószínűleg hibás*). A ‘–’ means there is no estimate. On the **GPT only, without JEV** path the estimate is GPT's: the probability of its answer, lowered to 50% when the field failed its field check; the tooltip says which (*GPT-becslés…*). GPT's estimates have their own band: green only from 98%, so a GPT field below 98% is ‘To check’ and shows under **Uncertain**. It is GPT's own estimate: GPT can be sure and still wrong. Below 98% on an accounting field (names, tax numbers, invoice number, dates, amounts) it also opens a to-do, ‘GPT is not sure enough of the value’ (*A GPT nem elég biztos az értékben*), so the document is not accepted automatically; on an address or another informational field it only shows the colour. With JEV this to-do never appears. A corrected field is always blue, because the estimate applied to the machine value. The colour is only a display aid, not a decision, and it does not prove that the value is correct.
- Source marker: ◉ the exact location is known, ◎ only an approximate location is known, ○ no location. Hover over the marker for an explanation.
- Fields with to-dos come first, then the ‘Likely wrong’ fields, then the rest.
- Below the selected field you see the ‘Source text:’ (*Forrásszöveg:*) with the page number; where relevant, a note that the value appears in several places; for a corrected field, the ‘Machine value:’ (*Gépi érték:*); and the ‘Other candidates:’ (*Más jelöltek:*) buttons.
- **On the image**, the value of the field being checked is highlighted in the colour of its band, line by line like a see-through marker, inside one thin frame drawn outside the text, so a value printed over several lines (an address) stays readable. Its other candidates have thin dashed boxes with a tag beside them; a candidate lying within the value shows only its tag. The image turns to the page of the field and scrolls the box into view. A dashed box is an approximate location (the line the machine picked from); a purple box is a location selected by hand. Selecting on the image is always on: clicking the words or dragging a rectangle selects text for the field being checked (section 7.4). The image bar has page buttons (‘‹ ›’) and zoom buttons (‘−’, the percentage to reset, ‘+’).
- If the document has no word layer (because of an earlier run or an old OCR result), the fields cannot be boxed. The interface tells you so; to get the boxes, run the processing again.

### 7.4 Checking and correcting values

Next to each field's value there are two buttons:

- **✓ (correct)** (*helyes*): saves this field's value, the one in the box (the machine value, or the one you typed, chose or selected), records that a person verified it, and closes the field's to-dos in this run, under your name. The field then shows **verified** (*ellenőrizve*) until its value changes. Only this field is saved; your unsaved changes to other fields stay in the working copy. If the box is empty, ✓ records that the document has no value for the field.
- **✗ (wrong, fix it)** (*hibás, javítom*): empties the field and puts the cursor in it, with the hint ‘Select the right value on the image, type it, or pick a candidate…’ (*Jelöld ki a helyes értéket a képen, írd be, vagy válassz jelöltet…*). Bring in the right value in one of the three ways below, then press ✓. Once a field has an unsaved change, **↺ (restore)** (*visszaállítás*) takes the place of ✗ and brings back the original value.

You can correct a value in three ways:

1. **Type** into the field's box. If you delete the value, it is saved as a ‘no value’ (*nincs érték*) correction. Amounts and quantities are shown and typed the Hungarian way: a comma is the decimal separator, and a space or a dot groups thousands. So `35,56` is 35.56, and `28.000`, `28 000` and `28000` are all 28 000. A form that could be read two ways, such as `28.5` for an amount, is not saved: the interface asks for a decimal comma (`28,50`) or a number without grouping (`28000`). A date can be typed in any common form: `2022-12-04`, `2022.12.04.`, `2022. december 4.`, `04.12.2022`, `4 Dec 2022`, `04-DEC-22`. A date whose day and month could be read two ways, such as `04/12/2022` (4 December or 12 April) or `04.12.22`, is not saved: the interface asks for the year first (`2022-12-04`) or the month's name (`4 Dec 2022`). After saving, the message names the value as recorded, for example ‘Saved. Recorded value: Net amount: 28 000’ (*Mentve. Rögzített érték: …*); a date is shown with the year first (`2022-12-04`).
2. **Choose another candidate:** the selected field's other candidates appear on the image in dashed boxes with a tag (‘72%’, ‘machine value’ (*gépi érték*), ‘possible location’ (*lehetséges hely*)), and as buttons in the panel. One click makes a candidate the field's value, as an unsaved correction.
3. **Select on the image** (always on when the document has a word layer): with the field being checked, click the words (clicking a word again removes it), or drag a rectangle. The system interprets the selected text according to the kind of field (date, amount, tax ID…) and shows the result (‘→ Field: value’). The **Enter into field** (*Beírás a mezőbe*) button, or Enter in the field's box, transfers the value. If the text cannot be interpreted, the interface says so (‘This text cannot be interpreted as a “…” value. Select something else.’ (*Ez a szöveg nem értelmezhető „…” értékként. Jelölj ki mást.*)). A selected date whose day and month could be read two ways is not entered either; the interface asks you to type it with the year first (*A kijelölt dátumban a nap és a hónap kétféleképpen is olvasható…*). The same kind of date found by the machine gets the to-do ‘Uncertain order of day and month’ (*A nap és a hónap sorrendje kétes*). The selected location is saved together with the correction.

### 7.5 Line lists

If the document has a line list (for example invoice line items or statement transactions), tabs appear at the top of the panel: ‘Fields’ (*Mezők*) and the name of the list with its number of rows; a ‘ •’ marker shows unsaved changes. The cells of the list can be edited (dates in any unambiguous form, stored as YYYY-MM-DD; amounts and quantities as in section 7.4), **Add row** (*Sor hozzáadása*) adds a new row, × deletes a row, and **Revert list** (*A lista visszaállítása*) discards your changes to the list. Clicking a row makes the image jump to where that row is. A row that failed a check is shown in red. The correction applies to the whole list; the machine list is kept unchanged alongside it.

### 7.6 Saving and conflicts

- The **Save correction** (*Javítás mentése*) button (or Ctrl+Enter) saves a new correction version; the machine value is kept alongside it. ‘Correction version: N’ (*Javítás verziója: N*) is shown at the bottom. You need a name to save.
- An unsaved correction (the working copy) is kept if you move to another item or reload the page. The browser warns you before you close the tab. Another browser tab cannot see it. **Discard all changes** (*Minden módosítás elvetése*) throws the working copy away. A change you make while a save is under way is kept: the save clears only what it sent, and the rest stays in the working copy for the next save.
- **Conflict:** if someone else saved to the same item in the meantime, your save does not silently overwrite their correction. Instead you see the message ‘Someone else saved this item in the meantime…’ (*Közben más is mentett erre a tételre…*) and a red box (‘A newer correction was saved for this item in the meantime (version N). Your working copy has been kept.’ (*A tételre közben újabb javítás került (verzió N). A munkapéldányod megmaradt.*)). **Apply to the new version** (*Alkalmazás az új verzióra*) moves your changes onto the new version; check them, then save again. **Discard working copy** (*Munkapéldány elvetése*) keeps the new version.
- Corrections on an approved run are locked (‘Corrections to an approved run are locked.’ (*A jóváhagyott futás javítása le van zárva.*)).

### 7.7 Keyboard shortcuts

The review works from the keyboard: when an item opens, the cursor is in its first field (under the filter) with the value selected, so typing replaces it.

| Key | What it does |
|---|---|
| Tab / ↓ | next field (its value selected); after the last field, Tab leaves the list as usual |
| Shift+Tab / ↑ | previous field |
| Enter | ✓: saves and verifies the field and goes to the next one; after the last field of the filter, to the next item with to-dos. If text selected on the image can be read as the field's value, the first Enter writes it into the box |
| typing / Delete | replaces / empties the value (Enter afterwards saves it; an empty value means the document has none) |
| Esc | brings back the original value of a changed field; otherwise it first clears the selection on the image, then leaves the box |
| PageDown / PageUp | next / previous item (in a field's box too) |
| Ctrl+Enter | saves every unsaved field at once (it does not mark them as verified) |
| outside a box: ↓ / ↑ (or j / k), n / p, Enter | next / previous field, next / previous item (n / p work on a line-list tab too), back into the field's box |

### 7.8 Reviewing emails

- **On the left is the email:** the subject, ‘From’ (*Feladó*), ‘To’ (*Címzett*), ‘Received’ (*Érkezett*), ‘Attachment’ (*Csatolmány*) and the text. Links cannot be clicked; instead, ‘link:’ and the host name are shown, and the full address appears when you hover over it. A notice warns you if intent recognition saw only the beginning of the email, or if the text may already have been cut off when it was downloaded.
- **On the right** are the to-dos with a **Resolved** button, and the **Detected intent** (*Felismert szándék*) with the model's estimate, or the marker ‘Corrected by hand (the machine said: …)’ (*Kézzel javítva (a gép szerint: …)*) / ‘Confirmed by hand’ (*Kézzel megerősítve*).
- **Correct the intent** (*Szándék javítása*): choose the correct intent. If it matches the current intent, the button reads **Confirm** (*Megerősítés*); otherwise it reads **Save correction**. When you save, the email's to-do for an uncertain intent is closed, and the **Suggested next step** (*Javasolt következő lépés*) (for example ‘Manual processing’ (*Kézi feldolgozás*), ‘Archive’ (*Archiválás*) or ‘Data extraction from the attachment (…)’ (*Adatkinyerés a csatolmányból (…)*)) is recalculated from the corrected intent.
- **Task proposals (only a person can accept them)** (*Feladatjavaslatok (elfogadni csak ember tud)*): shown only if task proposals are switched on in the processing settings. For each proposal you see the title, the action, the ‘Deadline’ (*Határidő*) and the ‘Assignee’ (only if the email states them word for word), and the quotes under ‘Evidence’ (*Bizonyíték*). Buttons: **Accept** (*Elfogadás*), **Reject** (*Elvetés*), and on an accepted proposal **Done** (*Elvégezve*) (recorded with your name and the time) and **Undo done** (*Elvégzés visszavonása*). Identical proposals are merged (‘N identical proposals merged’ (*N azonos javaslat összevonva*)). Proposals that failed the evidence check are listed in an expandable section, together with the parts that cannot be verified. No proposals are requested for emails to be archived (newsletters, notifications). Once you have decided on every proposal of an email, the to-do for its proposals (‘N task proposal(s) awaiting a decision’ (*N feladatjavaslat vár döntésre*)) closes by itself. If no proposal could be made, a ‘Task proposal failed (…)’ (*A feladatjavaslat nem sikerült (…)*) to-do is shown.
- **Attachment detection** (*Csatolmányok felismerése*) and **Attachment data** (*A csatolmányok adatai*): a PDF attachment runs as a separate document in the package. The ‘…: extraction result →’ (*…: az adatkinyerés eredménye →*) link takes you to the attachment's review view.
- A PDF attachment that cannot be read (corrupt, too large, or over the reading time or memory) is shown as ‘the PDF cannot be read’ (*a PDF nem olvasható*), and the email gets a to-do; the intent of the email is still recognised.

### 7.9 Managing documents

After a run, the expandable **Manage documents: open, download, remove** (*Iratok kezelése: megnyitás, letöltés, eltávolítás*) section sits below the workspace; before a run, it is the only content of Review. Each row has **Open** (*Megnyitás*) (in a new tab), **Download** and **Remove** (*Eltávolítás*). Removing needs two clicks (‘Sure? Click again’). It takes the item off the package's list; the file stays where it is, and the input of earlier runs does not change.

### 7.10 Word, Excel, text and CSV review

These documents open **Saved source** and **Native facts** instead of a PDF page. Word retains paragraph/table order and header/footer parts; Excel shows sheets, cell positions, empty and hidden content, and distinguishes formulas from their saved results without recalculating them. Text citations use exact character positions; CSV retains its rows, columns and literal text. The [reader guide](NATIVE_READERS.md) describes supported encodings and reading limits.

Each fact keeps its original **Machine proposal** beside the saved and editable value. Use its citation to inspect the source, edit the value if needed, then **Check and attach source** to bind an exact quote from a saved element. Unchecked quote text stays in the local draft. **Save corrections** saves the changes; **Confirm this fact** records the review. A late source check cannot restore a discarded draft.

Draft values and quote edits survive a reload. If another person saves first, your text is retained and saving is blocked until you explicitly review the refreshed correction. A draft for a different result remains separate. Reading coverage, extracted claims and factual correctness are different: a successful read does not prove that every needed fact was extracted or that a proposal is correct.

The summary above the facts names reading gaps in everyday words, one line per kind with a count (for example content kept only in the original, in 12 places), and the reason when an extraction stopped. The provider, the model and the raw reading messages are under **Technical details**. A fact's warnings (an unfilled template field, a value whose kind does not fit its property, a stale formula result) and its to-dos (for example JEV does not support fact 3) are shown as sentences; facts are counted from one.

In **Result**, the **Native facts** table joins the existing PDF views. Its **Source** column shows each cited text with a short place (a cell such as `Sheet1!B4`, `p. 2` for a PDF page, a pilcrow and the paragraph number for Word); the full citation data and the constant correctness column are hidden by default and can be shown under **Columns**. The machine states have everyday labels. Table downloads offer Excel, CSV and JSON with explicit row and column scope; **Full Excel package** includes native facts and reading summaries alongside the PDF sheets. Approval binds to the result version actually displayed. A changed version must be reviewed again; approved runs lock corrections. Reopening a saved source or restarting the service does not itself request another model answer. Technical storage and recovery details are in [Native document processing](NATIVE_PROCESSING.md).

## 8. Result

- By default you see the result of the latest run. If the package has several runs, a run picker appears.
- The views (only those that have data): **Emails** (*Levelek*), **Tasks** (*Feladatok*), **Documents** (*Iratok*), **Data points** (*Adatpontok*), **Line items** (*Tételsorok*), **Utility cost** (*Közmű-költség*) and **File names** (*Fájlnevek*). An email package opens on Emails, any other package on Data points.
  - ‘Documents’: one row per document (type, path, state, open to-dos and, for an email attachment, the subject of the email it came from) and one column per field.
  - ‘Data points’: one row per field (value, page, source text, location, whether it was corrected, and any to-do on the field).
  - ‘Line items’: the rows of the line lists.
  - Everywhere you see the valid data, that is, the machine value with any human correction applied. Clicking a document's name opens Review.
- Table rows can be selected with their checkboxes, and the selected rows can be downloaded on their own (section 3.1). The **Full Excel package** (*Teljes Excel-csomag*) button puts all of the run's tables (including the utility cost) into one Excel file with several sheets.
- **Utility cost:** the gross amount of utility invoices per point of consumption and utility, month by month. An invoice that covers several months is split in proportion to the days. A cell shows the amount, or ‘missing’ (*hiányzik*: no invoice covers the month), ‘partial’ (*részleges*: part of the month is not covered) or ‘overlap’ (*átfedés*: two invoices cover it). An * marks a settlement invoice. Informational rows do not count towards the total. Clicking a cell shows its source invoices, each with an ‘open’ (*megnyitás*) link. The report counts a duplicated invoice only once, and says so.
- **File names:** copies of the documents under uniform, content-based names, for example `2026-09-12_SZAMLA_Minta-Kft_SZ-2026-001234.pdf` (date first, then the type, the partner and the identifier, without accents). The original files never change; the copies are exact byte-for-byte copies of the processed documents. The table shows each document's ‘New file name’ (*Új fájlnév*), whether it is ready or goes to review (‘Folder’ (*Mappa*)), and ‘Why to review’ (*Miért ellenőrzendő*).
  - A copy goes into the `ellenorzendo` (to review) subfolder when its name rests on something uncertain: the document did not finish processing, its type is unknown or uncertain, a field of the name is empty, or an open to-do concerns a field of the name. Correcting that field in Review makes the name certain.
  - **Download as ZIP** (*Letöltés ZIP-ben*) gives the copies and a manifest (`jegyzek.csv`: which original became which name, with its fingerprint). **Write to the output folder** (*Kiírás a kimeneti mappába*) puts the same into a new subfolder of the output folder (section 10.2); nothing there is ever overwritten. A document whose source file changed since it was added is left out and listed in the manifest as ‘skipped’ (*kimaradt*).
- **Approval:**
  - For a trial run, the interface states that the result cannot be released; that needs a live run.
  - For a live run, the **Approve and release** (*Jóváhagyás és kiadás*) button is active only once the run has finished and no to-dos are open; until then the interface tells you how many to-dos remain. The button needs two clicks.
  - After approval, ‘Released: approved by …, …’ (*Kiadva: jóváhagyta …, …*) is shown. Approval locks the run's field corrections, intent corrections and task-proposal decisions; you can still mark an accepted task as ‘done’ (*elvégezve*). Approval cannot be undone from the interface. Downloads remain available afterwards.

## 9. My work today

The **My work today** link in the header shows the selected person's actions for the day: processing settings, starting and approving runs, corrections, resolving to-dos, task-proposal decisions, package changes and mailbox downloads. In the ‘Day’ (*Nap*) field you can also pick an earlier day. The table columns are ‘Time’ (*Időpont*), ‘Action’ (*Művelet*), ‘Work package’, ‘Detail’ (*Részlet*) and ‘Run’ (*Futás*).

## 10. Settings

The left-hand menu of Settings has seven items: Mailboxes (*Postafiókok*), Work folders (*Munkamappák*), Processing (*Feldolgozás*), Users, Appearance (*Megjelenés*), Language and System (*Rendszer*).

### 10.1 Mailboxes

Mailbox download brings in emails from the Outlook running on this computer.

- **What to read** (*Mit olvassunk*): ‘Mailbox address’ (*Postafiók címe*) (you can enter several, comma-separated, exactly as they appear in Outlook; addresses under ‘Previously used:’ (*Korábban használt:*) can be added or removed with one click), ‘Folder’ (*Mappa*) (comma-separated), ‘with subfolders’ (*almappákkal*), the period (‘The last days’ (*Az utolsó napok*) with the ‘Number of days’ (*Napok száma*) field, or ‘Date range’ (*Dátumtól dátumig*)), and ‘At most this many emails (0 = no limit)’ (*Legfeljebb ennyi levél (0 = nincs korlát)*).
- **How many emails? (free)** (*Hány levél? (ingyenes)*): a preview of how many emails fall in the period, how many of them are new, and how many were already read in (these are skipped).
- **Schedule** (only with the ‘last days’ period): choose a frequency (every 15 minutes, every 30 minutes, hourly, every 4 hours, daily), then **Save schedule** (*Ütemezés mentése*). In the **Schedules** (*Ütemezések*) table you can change the frequency, turn a schedule off and on, or delete it (**Delete** (*Törlés*) needs two clicks). The ‘Last’ (*Legutóbb*) column shows the result or error of the last download. A schedule only runs while the worker is running and Outlook is open.
- **Downloads** (*Letöltések*): the state of every download, the number of new emails, the work package created and any error. Known Outlook errors (for example ‘Outlook is not running on this computer…’ (*Az Outlook nem fut ezen a gépen…*)) are shown in the interface language, both here and in the ‘Last’ column.
- The worker does the download, and document processing waits in the meantime. The new emails become a work package, but no paid run starts on its own.

### 10.2 Work folders

A work folder (a watched folder) is a folder that the worker checks at the frequency you set; it turns new PDFs into a work package or adds them to the existing one. For each folder you can set: ‘Name’, ‘Full folder path’ (typed, or chosen with **Browse…** as in section 4), ‘Active’ (*Aktív*), ‘Include subfolders’ (*Almappák is*), the packaging (‘One shared package’ (*Egy közös csomag*) or ‘Daily packages’ (*Napi csomagok*)) and how often to ‘Check’ (*Átnézés*). The package gets the default processing settings; you can change them on the package. The **Add work folder** (*Munkamappa hozzáadása*), **Remove**, **Discard changes** (*Módosítások elvetése*) and **Save** buttons manage the list. If there are unsaved changes, leaving the page asks for confirmation. On a saved folder, **Check now** (*Átnézés most*) checks it immediately; a file that is still being written is left for the next check. The system only reads the source folder, and no paid run starts on its own.

Below the list, the **Output folder** (*Kimeneti mappa*) card sets where the content-named copies of a run are written (Result › File names). It is saved on its own with its **Save** button; an empty field clears it. It cannot be inside a watched work folder or contain one (the watcher would take the copies in again), and a work folder cannot be saved inside it either.

### 10.3 Processing

How the system works: what happens to a PDF document and to an email, what it needs, the steps, the result, what the person has to do, the default cost budget, every possible value of every setting with its meaning and budget, and **The paths compared** (*Az utak összevetése*): what the S and G paths do, whether they read line items, which services they call, their typical cost per document, their agreement with the golden set, which document types they work on and when each is better, with the source and date of the numbers. Nothing can be changed here; this is a read-only description.

### 10.4 Users

The names offered by **Who is working?**. Add a new name with the ‘New name’ (*Új név*) field and the **Add** (*Felvétel*) button; delete one with **Delete** (two clicks: ‘Sure? Click again’). Both are saved immediately. A name may contain letters, digits, spaces, dots, @ and hyphens, up to 64 characters. If the list is not empty, changes can only be made with a name on the list, and the package owner is also chosen from it.

### 10.5 Appearance

‘Theme’ (*Téma*): ‘Follow the system’ (*A rendszer szerint*), ‘Light’ (*Világos*) or ‘Dark’ (*Sötét*). ‘Density’ (*Sűrűség*): ‘Comfortable’ (*Tágas*) or ‘Compact’ (*Tömör*). Changes apply immediately and are remembered in this browser.

### 10.6 Language

‘Magyar’ or ‘English’ (each language name is shown in its own language); this is the same as the HU / EN buttons in the header (section 2.2).

### 10.7 System

- **Version** (*Verzió*): the running release version and commit (a fixed, identified state of the code in version control), and how long the service has been running. New code only takes effect after the service is restarted. ‘The running code contains uncommitted changes.’ (*A futó kód commitolatlan változást tartalmaz.*): the running code includes changes that have not been committed yet, so it is not exactly a released state. ‘The commit is unknown…’ (*A commit nem ismert…*): the service was started without version control.
- **A newer version is running** (*Újabb változat fut…*, a banner above the header on every page): the service was restarted with new code or the interface was rebuilt since this browser tab was loaded, so the tab still shows the old interface. **Reload** (*Újratöltés*) loads the new one; unsaved corrections are kept. The tab checks every minute and whenever you switch back to it. A restart of the same code shows no banner.
- **Worker** (*Feldolgozó*): ‘Running’ or ‘Not running’ (*Nem fut*), and the job-queue counts (queued, in progress, done, stopped, given up). **Stop** needs two clicks, and the worker stops after the item in progress. It can only be restarted with the start script.
- **Database backup** (*Adattár-mentés*): a verified copy of the database (packages, runs, corrections, decisions). It runs automatically every day at the configured time, and a copy also goes to a second location (for example a network drive). The panel's state is ‘OK’ (*Rendben*), ‘Attention’ (*Figyelem*) or ‘Error’ (*Hiba*), with the location of the local backup and of the copy below it. The ‘Internal documents’ (*Belső dokumentumok*) row shows the backup of the developer's local notes and has nothing to do with daily work. **Back up now** backs up immediately. If the last successful backup is older than the configured number of hours (36 by default), a warning appears.
- **Dependency audit** (*Csomag-ellenőrzés*): when the third-party program packages were last checked for known security flaws, and the result. The daily backup runs the check once a week. ‘Attention’ (*Figyelem*) means the check is missing, older than a week or incomplete; ‘Error’ (*Hiba*) means a known vulnerability was found, which the developer has to fix.
- **Calls with an uncertain outcome** (*Bizonytalan kimenetű hívások*): paid calls of which it is not known whether the provider carried them out, for example because the answer did not arrive in time after the request was sent. Until one is settled, its run's budget counts it at its maximum cost and the step is not repeated. Settle it with the actual cost from the provider's console (or none) and a note; it needs two clicks. Only a call whose outcome is uncertain can be settled: a call still in progress cannot, because it may still finish and cost money.
- **All runs** (*Minden futás*): every run of every package in one table.

## 11. Troubleshooting

| What you see | What it means | What to do |
|---|---|---|
| The browser cannot open the address, or the header shows the red ‘The local service is not reachable’; when you try an action, ‘The local service is not reachable. Is scripts\dev.ps1 start running?’ (*A helyi szolgáltatás nem érhető el. Fut a scripts\dev.ps1 start?*) | The local service is not running. | Start it with the start script. If it stops again, the last lines of the service log show why (Technical details). |
| ‘Worker not running’, runs stay ‘Queued’, and the mailbox and work folders are not updated | The worker has stopped or was stopped. | Run the start script again: it starts only the missing part. |
| When saving, ‘Someone else saved this item in the meantime…’, or a red box: ‘A newer correction was saved for this item in the meantime (version N)’ | Someone else saved a new correction to the same item in the meantime. | **Apply to the new version**, check, and save again; or **Discard working copy**. Your work has not been lost. |
| On approval: ‘The result changed after this page loaded (someone corrected it). Review it again, then approve.’ (*Az eredmény a megtekintés óta változott…*) | A correction was saved after you opened the page, for example in another tab. | Look at the refreshed result, then approve again. |
| On the settings, a start or a removal: ‘…changed meanwhile. We refreshed…’ (*…közben változott. Frissítettük…*) | The package or its settings were changed in the meantime. | Check the refreshed state and repeat the action. |
| ‘enter your name in the “Who is working?” field at the top…’ or ‘…select your name from the Users list in the “Who is working?” field’ (*…a „Ki dolgozik?” mezőben válaszd ki a neved a Felhasználók listájából*) | No name is selected, or the name is not on the list. | Choose a name in the header; if yours is missing, add it on the Settings › Users page. |
| On the mailbox preview, in the ‘Downloads’ table or in the ‘Last’ column: ‘Outlook is not running on this computer. Start it and try again.’ (*Az Outlook nem fut ezen a gépen. Indítsd el, és próbáld újra.*) | The download reads from the Outlook running on this computer. | Start Outlook and try again. |
| ‘This address does not match any Outlook account on this computer.’ (*Ez a cím egyetlen Outlook-fiókkal sem egyezik ezen a gépen.*) | The address you entered does not match any Outlook account. | Enter the address exactly as it appears in Outlook. |
| ‘The legacy Outlook script was not found in the old project; downloading does not work.’ (*A régi Outlook-szkript nem található a régi projektben; a letöltés nem működik.*) | The legacy script that does the download is missing. | Tell the owner of the computer; installation is described in the [setup guide](SETUP.md). |
| ‘The last successful backup was made N hours ago; the daily backup is probably not running.’ (*A legutóbbi sikeres mentés N órája készült; a napi mentés valószínűleg nem fut.*) | The daily automatic backup did not run. | Click **Back up now**, and ask the owner of the computer to check the scheduled task. |
| ‘The local backup is fine (…), but the copy to the second location failed: …’ (*A helyi mentés rendben…, de a másolat a második helyre nem sikerült: …*) | The second location (for example the network drive) was not reachable. | Check the network connection, then click **Back up now**. |
| ‘The last backup failed (…): sources: referenced source instances missing: …’ (*A legutóbbi mentés nem sikerült (…): sources: referenced source instances missing: …*) | The system's own copy of a document is missing or damaged, and no earlier backup holds an intact one, so a restore could not open that document. Earlier backups are not deleted until this is fixed. | Remove the named documents from their package and add the originals again if they are unchanged, then click **Back up now**. |
| To-do: ‘JEV was unavailable (…); check manually’ (*A JEV nem volt elérhető (…); ellenőrizd kézzel*), or for an email ‘Manual review: JEV was unavailable’ (*Kézi ellenőrzés: a JEV nem volt elérhető*) | JEV did not answer, or the item's budget ran out. The run did not stop because of this; it only sent this item for manual review. The brackets contain a short reason code (Technical details). | Check the fields on the image, correct them and click **Resolved**; or use **Rerun…** later (this involves new paid calls). |
| Blocker: ‘Missing source: …’ or ‘The source content changed since it was added: …’ | A document added before the system kept copies: its file has been moved, deleted or modified since it was added. | Put the original file back; or remove it from the package (section 7.9) and create a new package from the modified file. |
| Warning: ‘The original file has changed since it was added; the copy kept then is processed: …’ (or ‘…has disappeared…’) | The original was edited, moved or deleted after it was added. The run is not affected: it uses the copy kept then. | Nothing, if the change was not meant for this package. If the new version should be processed, create a new package from it. |
| Blocker: ‘The copy kept when it was added is missing or damaged: …’ | The system's own copy in its data folder was deleted or damaged. | Restore the data folder from a backup (Technical details); or remove the document from the package and add the original again if it is unchanged. |
| ‘This document has no word layer…’ (*Ehhez az irathoz nincs szóréteg…*) | This run of the document lacks the word positions. | Run the processing again. |
| ‘This folder is not among the allowed locations…’ (*Ez a mappa nincs az engedélyezett helyek között…*) | The folder restriction is switched on in the service settings (it is off by default). | Choose an allowed folder, or ask for the restriction to be changed (Technical details). |
| To-do: ‘Ambiguous decimal separator: …’ (*Kétértelmű tizedesjel: …*) | The number on the document can be read two ways (for example `12.34`, or a quantity printed as `1.153` on a document whose notation is unclear). | Check the value on the image and correct it if needed. |
| To-do: ‘The chosen value is only part of the number printed on the document: …’ (*A kiválasztott érték csak egy része az iraton nyomtatott számnak: …*) | A safety check: the chosen value is only a piece of a longer number printed on the document. | Check the value on the image and correct it. |
| ‘Could not save: a number can be read two ways…’ (*Nem sikerült menteni: egy szám kétféleképpen is olvasható…*) | A typed amount or quantity such as `28.5` could mean 28.5 or a mistyped 28 500. | Type it with a decimal comma (`28,50`) or without grouping (`28000`). |
| ‘The picker cannot open here; type the path instead.’ (*A választó ablak itt nem nyitható meg; írd be az útvonalat.*) | The local service cannot show a window on this computer (for example it runs without a desktop session). | Type or paste the path into the field. |
| ‘A picker is already open; close that one first.’ (*Már nyitva van egy választó ablak; előbb azt zárd be.*) | Another Browse… picker is still open, perhaps behind the browser. | Find it on the taskbar, then choose or cancel there. |
| ‘Unexpected error in the interface’ (*Váratlan hiba a felületen*) | A view ran into an error. | Click **Reload** (*Újratöltés*). Unsaved corrections are kept. |

## 12. What the interface does not do

- There is no login and no password. The **Who is working?** name only records the author; it is not a permission.
- It can only be reached from this computer; the service rejects requests from other computers and from other websites.
- It never starts a paid run on its own, and neither do work folders or mailbox schedules.
- It does not modify or delete source files. Deleting a package or removing an item only takes the files off the list.
- It does not open links in emails.
- The model's estimate, and agreement between two models, do not prove that a value is correct: that is why the interface asks for a human check.
- Restoring from a backup and restarting the worker are not done in the interface (Technical details).

## Technical details

**Starting and stopping** (from the project root, in PowerShell; installation: [SETUP](SETUP.md)):

```powershell
.\scripts\dev.ps1 start    # local service (127.0.0.1:8930) + one worker in the background; parts already running are not restarted
.\scripts\dev.ps1 status   # whether the service and the worker are running, and how many jobs are waiting
.\scripts\dev.ps1 stop     # the worker exits after the item in progress; the service stops immediately
```

- **Address:** `http://127.0.0.1:8930/`. The interface calls the `/api/...` endpoints. `/api/health` supplies the data for the Version card (version, commit, uncommitted changes, start time) and for the newer-version banner (`ui_build`: a fingerprint of the UI build served now, read on every request). The clickable endpoint list (`/api/docs`) is switched off. The security settings are described in the [security notes](../SECURITY.md).
- **Service logs:** `runs\logs\api.log` and `runs\logs\worker.log`; the start script's output: `runs\dev\*.log`.
- **Command-line equivalents:** `python -m jav.cli worker-status`, `worker-stop`, `backup`; for a paid call with an uncertain outcome: `calls-uncertain`, `calls-resolve <id> [--cost USD] --note N`. Restoring from a backup is done by hand, with the service stopped: [SETUP 6.](SETUP.md). The daily backup is started by Windows Task Scheduler (`scripts\backup-task.ps1`).
- **The bracketed reason of a JEV to-do:** `budget_exceeded` (the item's budget ran out), `uncertain_attempt` (the outcome of an earlier paid attempt is unknown and has to be settled by hand); any other value is an error or a timeout of the service.
- **Configuration files** (details: [configuration files guide](CONFIGS.md)):
  - the processing and its settings: `configs/recipes.json` (internally still called recipes; the UI offers only the active `processing`); their explanatory texts and the comparison of the paths: `configs/recipe_help.json`; moving old packages onto the processing: `python -m jav.cli processing-migrate [--write]`;
  - confidence bands (`confidence_bands`, 0.9 and 0.5 by default), backup (`backup`: time, number of copies kept, `max_age_hours`) and folder restriction (`restrict_paths`, `JAV_API_ROOTS`): `configs/service.json`;
  - Hungarian names of fields and document types: `configs/field_labels.json`; email intents: `configs/intents.json`; task-proposal actions: `configs/email_tasks.json`.
- **Data stored in the browser** (per viewer, not stored in the database): name `jav.actor`, language `jav.ui-language`, appearance `jav.appearance`, column visibility `jav.table.<table>.cols`, the image/panel ratio `jav.review.split` (on the line-list tab `jav.review.split.list`); the working copy, per tab: `jav.drafts` (sessionStorage).
- **Source code:** the interface is in `ui/src/` (views: `views/`, review: `review/`, labels: `labels.ts`, English translation: `i18n/en-*.json`); the service is `jav/api.py`, the table columns are in `jav/datasets.py`, the next step in `jav/work_views.py`. Structure: [architecture](../ARCHITECTURE.md), section 8.
- **Main labels in Hungarian** (the interface's default language):

| English | Hungarian |
|---|---|
| Work packages · Settings | Munkacsomagok · Beállítások |
| Who is working? · My work today | Ki dolgozik? · Mai munkám |
| New work package · Manage package | Új munkacsomag · Csomag kezelése |
| Processing · Review · Result | Feldolgozás · Ellenőrzés · Eredmény |
| Trial run · Live run · Rerun | Próbafutás · Éles futás · Újrafuttatás |
| Resolved · Save correction · Select on image | Rendezve · Javítás mentése · Kijelölés a képen |
| Approve and release · Back up now | Jóváhagyás és kiadás · Mentés most |
