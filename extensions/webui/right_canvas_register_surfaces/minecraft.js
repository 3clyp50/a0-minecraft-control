import { store } from '/plugins/minecraft_control/webui/store.js?v=0.6.0';
export default function(surfaces) {
    surfaces.registerSurface({id: 'minecraft', title: 'Minecraft', icon: 'deployed_code', order: 45,
        modalPath: '/plugins/minecraft_control/webui/main.html?v=0.6.0',
        open() { store.onOpen(); }, close() { store.cleanup(); }});
}
