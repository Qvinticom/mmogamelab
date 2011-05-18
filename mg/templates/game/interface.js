var admin_root = '';
var Game = {
	app: '[%app%]',
	domain: '[%domain%]',
	character: '[%character%]'
};

Game.fixupContentEl = function(el) {
	var def = Ext.get('default-' + el.contentEl);
	if (!def) {
		Ext.alert('Missing element: default-' + el.contentEl);
		return el;
	}
	if (Ext.getDom(el.contentEl)) {
		Ext.get(def.id).remove();
		if (el.loadHeight)
			el.height = Ext.get(el.contentEl).getHeight();
	} else {
		if (el.loadHeight)
			el.height = def.getHeight();
		def.id = el.contentEl;
		def.dom.id = el.contentEl;
	}
	return el;
};

Game.setup_game_layout = function() {
	var topmenu = this.fixupContentEl({
		id: 'topmenu-container',
		xtype: 'box',
		height: 40,
		contentEl: 'topmenu'
	});
	new Ext.Container({
		id: 'chat-frame-layout',
		renderTo: 'chat-frame-content',
		layout: 'border',
		height: '100%',
		items: [[%if layout.chat_channels%]this.fixupContentEl({
			xtype: 'box',
			region: 'north',
			loadHeight: true,
			contentEl: 'chat-buttons'
		}),[%end%]this.fixupContentEl({
			xtype: 'box',
			region: 'center',
			contentEl: 'chat-box'
		}), this.fixupContentEl({
			xtype: 'box',
			loadHeight: true,
			region: 'south',
			contentEl: 'chat-input'
		})]
	});
	var chat = this.fixupContentEl({
		id: 'chat-frame-container',
		xtype: 'container',
		contentEl: 'chat-frame',
		onLayout: function(shallow, forceLayout) {
			if (shallow !== true) {
				Ext.getCmp('chat-frame-layout').doLayout(false, forceLayout);
			}
		}
	});
	new Ext.Container({
		id: 'chat-roster-content',
		applyTo: 'chat-roster-content',
		height: '100%'
	});
	var roster = this.fixupContentEl({
		id: 'roster-container',
		xtype: 'container',
		contentEl: 'chat-roster',
		onLayout: function(shallow, forceLayout) {
			if (shallow !== true) {
				Ext.getCmp('chat-roster-content').doLayout(false, forceLayout);
			}
		}
	});
	var main = {
		id: 'main-iframe',
		xtype: 'iframepanel',
		border: false,
		defaultSrc: '[%main_init%]',
		frameConfig: {
			name: 'main'
		}
	};

	[%if layout.scheme == 1%]
	topmenu.region = 'north';
	chat.region = 'center';
	chat.minWidth = 200;
	roster.region = 'east';
	roster.split = true;
	roster.width = 300;
	roster.minSize = 300;
	main.region = 'center';
	main.minHeight = 200;
	var content = new Ext.Container({
		id: 'page-content',
		layout: 'border',
		items: [
			topmenu,
			{
				id: 'chat-and-roster',
				xtype: 'container',
				region: 'south',
				height: 250,
				minHeight: 100,
				layout: 'border',
				split: true,
				items: [chat, roster]
			},
			main
		]
	});
	[%elsif layout.scheme == 2%]
	topmenu.region = 'north';
	roster.region = 'east';
	roster.width = 300;
	roster.minSize = 300;
	roster.split = true;
	chat.region = 'south';
	chat.split = true;
	chat.height = 250;
	chat.minHeight = 100;
	main.region = 'center';
	main.minHeight = 200;
	var content = new Ext.Container({
		id: 'page-content',
		layout: 'border',
		items: [
			topmenu,
			roster,
			{
				id: 'main-and-chat',
				xtype: 'container',
				region: 'center',
				minWidth: 300,
				layout: 'border',
				items: [main, chat]
			}
		]
	});
	[%elsif layout.scheme == 3%]
	topmenu.region = 'north';
	main.region = 'center';
	main.minWidth = 300;
	roster.region = 'center';
	roster.minHeight = 100;
	chat.region = 'south';
	chat.minHeight = 100;
	chat.height = 300;
	chat.split = true;
	var content = new Ext.Container({
		id: 'page-content',
		layout: 'border',
		items: [
			topmenu,
			main,
			{
				id: 'roster-and-chat',
				xtype: 'container',
				region: 'east',
				width: 300,
				minWidth: 300,
				layout: 'border',
				split: true,
				items: [roster, chat]
			}
		]
	});
	[%else%]
	var content = new Ext.Container({
		id: 'page-content',
		html: gt.gettext('Misconfigured layout scheme')
	});
	[%end%]
	var margins = new Array();
	[%if layout.marginleft%]
	margins.push(this.fixupContentEl({
		xtype: 'box',
		width: [%layout.marginleft%],
		region: 'west',
		contentEl: 'margin-left'
	}));
	[%end%]
	[%if layout.marginright%]
	margins.push(this.fixupContentEl({
		xtype: 'box',
		width: [%layout.marginright%],
		region: 'east',
		contentEl: 'margin-right'
	}));
	[%end%]
	[%if layout.margintop%]
	margins.push(this.fixupContentEl({
		xtype: 'box',
		height: [%layout.margintop%],
		region: 'north',
		contentEl: 'margin-top'
	}));
	[%end%]
	[%if layout.marginbottom%]
	margins.push(this.fixupContentEl({
		xtype: 'box',
		height: [%layout.marginbottom%],
		region: 'south',
		contentEl: 'margin-bottom'
	}));
	[%end%]
	if (margins.length) {
		content.region = 'center';
		margins.push(content);
		new Ext.Viewport({
			id: 'game-viewport',
			layout: 'border',
			items: margins
		});
	} else {
		new Ext.Viewport({
			id: 'game-viewport',
			layout: 'fit',
			items: content
		});
	}
};

Game.setup_cabinet_layout = function() {
	new Ext.Viewport({
		id: 'cabinet-viewport',
		layout: 'fit',
		items: this.fixupContentEl({
			xtype: 'box',
			contentEl: 'cabinet-content'
		})
	});
};

Ext.onReady(function() {
	Ext.QuickTips.init();
	Ext.form.Field.prototype.msgTarget = 'under';
	wait([[%foreach module in js_modules%]'[%module.name%]'[%unless module.lst%],[%end%][%end%]], function() {
		[%+ foreach statement in js_init%][%statement +%]
		[%+ end%]
	});
});
