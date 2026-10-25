# MoneyLens website

A static, two-page explanation of the MoneyLens skills, workflow, setup, and
privacy/usage policy. Built with Bun, Vite, vanilla JavaScript, and Tailwind CSS 4.
Fonts and core palette are shared with the skill report in `../src/brand.css`.
Vendored font sources live in `../src/fonts`; their OFL notices also ship in
`public/font-licenses.txt`.
All example report data is fictional.
The website and favicon reuse the magnifying-glass/chart icon from the skill's
report template (`src/report.html`), using the report's Sage palette.

## Development

Use Bun 1.4.3 (the same version pinned by CI):

```sh
cd website
bun install --frozen-lockfile
bun run dev
```

Open the printed localhost URL. To check the production output:

```sh
bun run build
bun run preview
```

The build verifies both pages, local assets, and cross-page anchors. It rejects
root-relative asset links (which break GitHub project sites), symlinks, and
unexpected/private file types in the upload directory. The website has its own
package and lockfile so it does not change the plugin's build dependencies.

## GitHub Pages

The repository workflow `.github/workflows/pages.yml` builds on website or shared
brand/font changes in pull requests and pushes to `main`. It uploads **only `website/dist`** using
`actions/upload-pages-artifact`, then a separate deployment job publishes that
artifact using `actions/deploy-pages`. Pull requests build without deploying.
No generated branch, committed build output, personal report, plugin bundle,
email credentials, or custom deployment secret is required.

One-time repository setup:

1. Open **Settings → Pages → Build and deployment**.
2. Select **GitHub Actions** as the source.
3. Push the website/workflow to `main`, or run **Website · GitHub Pages** manually
   from `main` in the Actions tab.

The expected project-site address is `https://roulpriya.github.io/moneylens/`.
The deployment job reports the actual published URL. Relative assets and page
links also support a custom domain without a rebuild-time repository name.
If the `github-pages` environment requires approval, approve the deployment in
GitHub after the build completes.

## Updating content

- `index.html`: overview, fictional report, working steps, and installation.
- `policy.html`: privacy and usage policy. Update its revision date when policy
  text changes. Verify claims against the maintained skill and Python runtime.
- `src/main.js`: keyboard-accessible workflow tabs and copy command.
- `src/style.css`: Tailwind import, theme tokens, and responsive page styling.

The explanatory sample is not an embedded personal MoneyLens report. Keep all
financial data outside this directory and the Pages artifact.
