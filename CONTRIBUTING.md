# תרומה לפרויקט · Contributing

*English below.*

תודה שאתם רוצים לשפר את הפלאגין! כל שינוי נכנס דרך Pull Request, ומתמזג רק אחרי בדיקה ואישור של מנהל הפרויקט ([@Chaim-GurArie](https://github.com/Chaim-GurArie)).

## איך תורמים

1. **פתחו Issue קודם** לשינוי גדול (סוכן חדש, שינוי במבנה הצינור, שינוי בכללי הליבה), כדי שנסכים על הכיוון לפני שאתם משקיעים זמן. תיקוני באגים קטנים אפשר לשלוח ישר.
2. **Fork** למאגר, ויצירת ענף עם שם ברור: `fix/render-pages-commas`, `feature/apa-chicago-profile`.
3. **בצעו את השינוי** ובדקו אותו (ראו "בדיקה" למטה).
4. **פתחו Pull Request** אל `main` ומלאו את התבנית: מה השתנה, למה, ואיך בדקתם.
5. אני אעבור על השינוי, ואולי אבקש תיקונים. אחרי האישור הוא ימוזג.

## מה חשוב לשמור עליו

- **כללי הליבה (`skills/review/resources/core-rules.md`) נעולים.** הם מה שמונע מהמערכת להמציא מקורות ומספרים. שינוי שמחליש אותם לא יתקבל. אם יש לכם הצעה לשינוי בהם, פתחו Issue לדיון.
- **אל תעלו מאמרים, עבודות של סטודנטים או תיקיות `review-output`.** גם לא כדוגמה, בגלל זכויות יוצרים ופרטיות. דוגמאות בדיקה צריכות להיות קבצים שיצרתם בעצמכם או קבצים ברישיון פתוח.
- **סקריפטי Python** צריכים לרוץ על Python 3.9 ומעלה, ב־Windows וב־Mac, ולהשתמש רק בספריות שב־`requirements.txt` (או להוסיף אליו ולהסביר למה).
- **הודעות למשתמש** בשפה פשוטה, בלי מונחים טכניים, בעברית כברירת מחדל. הקהל הוא סטודנטים, לא מפתחים.
- **הוראות לסוכנים** (`agents/*.md`, `SKILL.md`) נכתבות באנגלית, קצרות ומדויקות.

## בדיקה

לפני שליחת PR:
- `python3 -m py_compile skills/review/scripts/*.py`
- הריצו את הפלאגין המקומי על תיקייה קטנה עם 3–5 מאמרים פתוחים:
  `/plugin marketplace add <נתיב לתיקיית ה־fork>` ואז `/plugin install lit-review@lit-review-marketplace`
- ציינו ב־PR מה הרצתם ומה ראיתם.

## דיווח על באגים

פתחו Issue עם: מה עשיתם, מה ציפיתם שיקרה, מה קרה בפועל, מערכת הפעלה וגרסת Python. אם הבעיה קשורה לקובץ PDF מסוים, תארו אותו (סרוק? עברית? טבלאות?) אבל אל תצרפו אותו אם אינו ברישיון פתוח.

---

## English

Thanks for helping! All changes go through a pull request and are merged only after review and approval by the maintainer ([@Chaim-GurArie](https://github.com/Chaim-GurArie)).

1. **Open an issue first** for anything large (a new agent, pipeline changes, changes to core rules). Small bug fixes can go straight to a PR.
2. **Fork** and create a descriptively named branch.
3. **Make and test** your change: `python3 -m py_compile skills/review/scripts/*.py`, then run the plugin locally on a small set of openly licensed PDFs.
4. **Open a PR** against `main` and fill in the template.

Ground rules:
- `core-rules.md` is locked. PRs that weaken source fidelity (no outside sources, no invented numbers, a citation for every claim) will not be accepted.
- Never commit articles, student papers or `review-output` folders.
- Scripts must run on Python 3.9+ on Windows and macOS, using only the packages in `requirements.txt`.
- User-facing messages stay plain and non-technical. Agent instructions stay in concise English.

By contributing you agree that your contribution is licensed under the project's MIT license.
