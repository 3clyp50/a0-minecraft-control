import { createStore } from '/js/AlpineStore.js';
import { callJsonApi } from '/js/api.js';
import { toastFrontendError, toastFrontendSuccess } from '/components/notifications/notification-store.js';
import { renderSafeMarkdown } from '/js/safe-markdown.js';
import { store as pluginSettings } from '/components/plugins/plugin-settings-store.js';

export const store = createStore('minecraft', {
    state: {}, prompt: '', tab: 'console', timer: null, loading: false, sending: false, action: '', version: '', setupOpen: null,
    profile() { return this.state.setup?.profiles?.installed?.find(item => item.game_version === this.version); },
    outputHtml() { return renderSafeMarkdown(this.state.output || '—'); },
    settings() { return pluginSettings.openConfig('minecraft_control'); },
    async refresh() {
        if (this.loading) return;
        this.loading = true;
        try { this.state = await callJsonApi('/api/plugins/minecraft_control/control', {
            action: 'status', context_id: window.Alpine?.store('chats')?.selected || ''});
            if (this.setupOpen === null) this.setupOpen = !this.state.online;
            if (!this.version) this.version = this.state.setup?.profiles?.recommended || '';
        }
        catch (error) { this.cleanup(); toastFrontendError(error.message, 'Minecraft'); }
        finally { this.loading = false; }
    },
    async onOpen() {
        if (this.timer) return;
        this.timer = setInterval(() => this.refresh(), 2000);
        await this.refresh();
        if (this.state.launcher?.ready && !this.state.online && !this.state.setup?.profiles) await this.send('profile_versions');
    },
    cleanup() { clearInterval(this.timer); this.timer = null; },
    async send(action) {
        if (this.sending) return;
        this.sending = true;
        this.action = action;
        try {
            const result = await callJsonApi('/api/plugins/minecraft_control/control', {action, prompt: this.prompt, version: this.version,
                context_id: window.Alpine?.store('chats')?.selected || ''});
            if (result.setup) {
                this.state.setup = result.setup;
                const profiles = result.setup.profiles;
                if (profiles && !profiles.versions?.includes(this.version)) this.version = profiles.recommended || '';
            }
            if (action === 'install_profile') toastFrontendSuccess(`Agent Zero ${this.version} is ready in Minecraft Launcher.`, 'Minecraft');
            if (action === 'build') { this.prompt = ''; this.state.busy = true; this.state.phase = 'Queued'; }
            else await this.refresh();
        } catch (error) { toastFrontendError(error.message, 'Minecraft'); }
        finally { this.sending = false; this.action = ''; }
    },
    coordinates() {
        const p = this.state.player;
        return p && Number.isFinite(p.x) ? [p.x, p.y, p.z].map(Math.floor).join(' / ') : '—';
    },
    items() {
        const inventory = this.state.inventory || {};
        const items = [...(inventory.hotbar || []), ...(inventory.main || []),
            ...(inventory.armor || []), inventory.offhand];
        return items.filter(item => item && (item.count || 0) > 0);
    }
});
