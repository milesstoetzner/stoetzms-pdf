import {defineConfig} from 'vitepress'

// https://vitepress.dev/reference/site-config
export default defineConfig({
    title: 'pdf.stoetz.ms',
    description: 'Assemble PDFs into one structured document from a declarative YAML file.',
    base: '/',
    themeConfig: {
        // https://vitepress.dev/reference/default-theme-config
        nav: [
            {text: 'Home', link: '/'},
            {text: 'User Guide', link: '/user-guide'},
            {text: 'Configuration', link: '/configuration'},
            {text: 'Customization', link: '/customization'},
            {text: 'Development', link: '/development'},
        ],

        socialLinks: [{icon: 'github', link: 'https://github.com/milesstoetzner/stoetzms-pdf'}],
    },
    appearance: false,
})
