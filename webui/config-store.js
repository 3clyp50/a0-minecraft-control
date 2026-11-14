import { createStore } from '/js/AlpineStore.js';
import { callJsonApi } from '/js/api.js';
import { toastFrontendError } from '/components/notifications/notification-store.js';
export const store = createStore('minecraftConfig', {
    presets: [], ready: false,
    async load(config) {
        for (const key of ['auto_resume', 'verify_screenshot', 'chat_relay']) {
            if (config[key] === undefined) config[key] = true;
        }
        this.ready = false;
        try {
            this.presets = (await callJsonApi('/api/plugins/minecraft_control/control', {action: 'presets'})).presets;
            this.ready = true;
        }
        catch (error) { toastFrontendError(error.message, 'Minecraft'); }
    }
});
