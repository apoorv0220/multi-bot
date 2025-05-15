<?php
/**
 * Plugin Name: Migraine.ie AI Chatbot
 * Description: Integrate the Migraine.ie AI-powered chatbot into your WordPress site.
 * Version: 1.0.0
 * Author: Migraine.ie Team
 * Text Domain: migraine-chatbot
 */

// Exit if accessed directly
if (!defined('ABSPATH')) {
    exit;
}

class MigraineChatbot {
    /**
     * Constructor
     */
    public function __construct() {
        // Register activation and deactivation hooks
        register_activation_hook(__FILE__, array($this, 'activate'));
        register_deactivation_hook(__FILE__, array($this, 'deactivate'));
        
        // Add chatbot widget to footer
        add_action('wp_footer', array($this, 'render_chatbot_widget'));
        
        // Add admin menu
        add_action('admin_menu', array($this, 'add_admin_menu'));
        
        // Add custom URL management
        add_action('init', array($this, 'create_custom_url_table'));
    }
    
    /**
     * Plugin activation
     */
    public function activate() {
        // Create custom URL table if it doesn't exist
        $this->create_custom_url_table();
        
        // Set default options
        $default_options = array(
            'chatbot_enabled' => true,
            'custom_urls_enabled' => true,
            'api_url' => 'http://localhost:8000',
        );
        
        update_option('migraine_chatbot_settings', $default_options);
    }
    
    /**
     * Plugin deactivation
     */
    public function deactivate() {
        // Nothing to do for now
    }
    
    /**
     * Create custom URL table
     */
    public function create_custom_url_table() {
        global $wpdb;
        
        $table_name = $wpdb->prefix . 'custom_urls';
        $charset_collate = $wpdb->get_charset_collate();
        
        // Check if table exists
        if ($wpdb->get_var("SHOW TABLES LIKE '$table_name'") != $table_name) {
            $sql = "CREATE TABLE $table_name (
                id mediumint(9) NOT NULL AUTO_INCREMENT,
                url varchar(255) NOT NULL,
                title varchar(255) NOT NULL,
                description text,
                active tinyint(1) DEFAULT 1 NOT NULL,
                created_at datetime DEFAULT CURRENT_TIMESTAMP NOT NULL,
                PRIMARY KEY  (id)
            ) $charset_collate;";
            
            require_once(ABSPATH . 'wp-admin/includes/upgrade.php');
            dbDelta($sql);
            
            // Add some example URLs
            $wpdb->insert(
                $table_name,
                array(
                    'url' => 'https://www.who.int/news-room/fact-sheets/detail/headache-disorders',
                    'title' => 'WHO - Headache Disorders',
                    'description' => 'Factsheet about headache disorders from the World Health Organization',
                    'active' => 1
                )
            );
        }
    }
    
    /**
     * Add admin menu
     */
    public function add_admin_menu() {
        add_menu_page(
            'Migraine Chatbot',
            'Migraine Chatbot',
            'manage_options',
            'migraine-chatbot',
            array($this, 'render_admin_page'),
            'dashicons-format-chat',
            30
        );
        
        add_submenu_page(
            'migraine-chatbot',
            'Settings',
            'Settings',
            'manage_options',
            'migraine-chatbot',
            array($this, 'render_admin_page')
        );
        
        add_submenu_page(
            'migraine-chatbot',
            'Custom URLs',
            'Custom URLs',
            'manage_options',
            'migraine-chatbot-urls',
            array($this, 'render_urls_page')
        );
    }
    
    /**
     * Render admin page
     */
    public function render_admin_page() {
        // Handle form submission
        if (isset($_POST['submit'])) {
            // Verify nonce
            if (!isset($_POST['migraine_chatbot_nonce']) || !wp_verify_nonce($_POST['migraine_chatbot_nonce'], 'migraine_chatbot_settings')) {
                echo '<div class="notice notice-error"><p>Invalid nonce. Please try again.</p></div>';
                return;
            }
            
            // Save settings
            $options = array(
                'chatbot_enabled' => isset($_POST['chatbot_enabled']) ? true : false,
                'custom_urls_enabled' => isset($_POST['custom_urls_enabled']) ? true : false,
                'api_url' => sanitize_text_field($_POST['api_url']),
            );
            
            update_option('migraine_chatbot_settings', $options);
            echo '<div class="notice notice-success"><p>Settings saved successfully!</p></div>';
        }
        
        // Get current settings
        $options = get_option('migraine_chatbot_settings', array(
            'chatbot_enabled' => true,
            'custom_urls_enabled' => true,
            'api_url' => 'http://localhost:8000',
        ));
        
        ?>
        <div class="wrap">
            <h1>Migraine.ie AI Chatbot Settings</h1>
            
            <form method="post" action="">
                <?php wp_nonce_field('migraine_chatbot_settings', 'migraine_chatbot_nonce'); ?>
                
                <table class="form-table">
                    <tr>
                        <th scope="row">Enable Chatbot</th>
                        <td>
                            <input type="checkbox" name="chatbot_enabled" <?php checked($options['chatbot_enabled']); ?> />
                            <p class="description">Show the chatbot widget on your site</p>
                        </td>
                    </tr>
                    
                    <tr>
                        <th scope="row">Enable Custom URLs</th>
                        <td>
                            <input type="checkbox" name="custom_urls_enabled" <?php checked($options['custom_urls_enabled']); ?> />
                            <p class="description">Include content from custom URLs in search results</p>
                        </td>
                    </tr>
                    
                    <tr>
                        <th scope="row">API URL</th>
                        <td>
                            <input type="text" name="api_url" value="<?php echo esc_attr($options['api_url']); ?>" class="regular-text" />
                            <p class="description">URL of the chatbot API (without trailing slash)</p>
                        </td>
                    </tr>
                </table>
                
                <p class="submit">
                    <input type="submit" name="submit" class="button button-primary" value="Save Settings" />
                </p>
            </form>
        </div>
        <?php
    }
    
    /**
     * Render URLs page
     */
    public function render_urls_page() {
        global $wpdb;
        
        $table_name = $wpdb->prefix . 'custom_urls';
        
        // Handle form submission
        if (isset($_POST['submit'])) {
            // Verify nonce
            if (!isset($_POST['migraine_chatbot_urls_nonce']) || !wp_verify_nonce($_POST['migraine_chatbot_urls_nonce'], 'migraine_chatbot_urls')) {
                echo '<div class="notice notice-error"><p>Invalid nonce. Please try again.</p></div>';
                return;
            }
            
            // Add new URL
            if (!empty($_POST['url']) && !empty($_POST['title'])) {
                $wpdb->insert(
                    $table_name,
                    array(
                        'url' => esc_url_raw($_POST['url']),
                        'title' => sanitize_text_field($_POST['title']),
                        'description' => sanitize_textarea_field($_POST['description']),
                        'active' => isset($_POST['active']) ? 1 : 0
                    )
                );
                
                echo '<div class="notice notice-success"><p>URL added successfully!</p></div>';
            }
            
            // Update existing URLs
            if (isset($_POST['url_id']) && is_array($_POST['url_id'])) {
                foreach ($_POST['url_id'] as $id) {
                    $id = intval($id);
                    
                    // Delete
                    if (isset($_POST['delete_' . $id])) {
                        $wpdb->delete($table_name, array('id' => $id));
                        continue;
                    }
                    
                    // Update
                    $wpdb->update(
                        $table_name,
                        array(
                            'url' => esc_url_raw($_POST['url_' . $id]),
                            'title' => sanitize_text_field($_POST['title_' . $id]),
                            'description' => sanitize_textarea_field($_POST['description_' . $id]),
                            'active' => isset($_POST['active_' . $id]) ? 1 : 0
                        ),
                        array('id' => $id)
                    );
                }
                
                echo '<div class="notice notice-success"><p>URLs updated successfully!</p></div>';
            }
        }
        
        // Get all URLs
        $urls = $wpdb->get_results("SELECT * FROM $table_name ORDER BY created_at DESC");
        
        ?>
        <div class="wrap">
            <h1>Manage Custom URLs</h1>
            
            <p>Add external URLs to include in the chatbot's knowledge base. These pages will be crawled and indexed weekly.</p>
            
            <form method="post" action="">
                <?php wp_nonce_field('migraine_chatbot_urls', 'migraine_chatbot_urls_nonce'); ?>
                
                <h2>Add New URL</h2>
                <table class="form-table">
                    <tr>
                        <th scope="row">URL</th>
                        <td>
                            <input type="url" name="url" class="regular-text" required />
                            <p class="description">Full URL including http:// or https://</p>
                        </td>
                    </tr>
                    
                    <tr>
                        <th scope="row">Title</th>
                        <td>
                            <input type="text" name="title" class="regular-text" required />
                            <p class="description">Name of the source</p>
                        </td>
                    </tr>
                    
                    <tr>
                        <th scope="row">Description</th>
                        <td>
                            <textarea name="description" rows="3" class="large-text"></textarea>
                            <p class="description">Optional description of the content</p>
                        </td>
                    </tr>
                    
                    <tr>
                        <th scope="row">Active</th>
                        <td>
                            <input type="checkbox" name="active" checked />
                            <p class="description">Include this URL in the knowledge base</p>
                        </td>
                    </tr>
                </table>
                
                <p class="submit">
                    <input type="submit" name="submit" class="button button-primary" value="Add URL" />
                </p>
                
                <h2>Existing URLs</h2>
                
                <?php if (empty($urls)) : ?>
                    <p>No custom URLs added yet.</p>
                <?php else : ?>
                    <table class="wp-list-table widefat fixed striped">
                        <thead>
                            <tr>
                                <th>URL</th>
                                <th>Title</th>
                                <th>Description</th>
                                <th>Active</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>
                            <?php foreach ($urls as $url) : ?>
                                <input type="hidden" name="url_id[]" value="<?php echo esc_attr($url->id); ?>" />
                                <tr>
                                    <td>
                                        <input type="url" name="url_<?php echo esc_attr($url->id); ?>" value="<?php echo esc_url($url->url); ?>" class="regular-text" required />
                                    </td>
                                    <td>
                                        <input type="text" name="title_<?php echo esc_attr($url->id); ?>" value="<?php echo esc_attr($url->title); ?>" class="regular-text" required />
                                    </td>
                                    <td>
                                        <textarea name="description_<?php echo esc_attr($url->id); ?>" rows="2" class="large-text"><?php echo esc_textarea($url->description); ?></textarea>
                                    </td>
                                    <td>
                                        <input type="checkbox" name="active_<?php echo esc_attr($url->id); ?>" <?php checked($url->active); ?> />
                                    </td>
                                    <td>
                                        <label>
                                            <input type="checkbox" name="delete_<?php echo esc_attr($url->id); ?>" />
                                            Delete
                                        </label>
                                    </td>
                                </tr>
                            <?php endforeach; ?>
                        </tbody>
                    </table>
                    
                    <p class="submit">
                        <input type="submit" name="submit" class="button button-primary" value="Update URLs" />
                    </p>
                <?php endif; ?>
            </form>
        </div>
        <?php
    }
    
    /**
     * Render chatbot widget
     */
    public function render_chatbot_widget() {
        // Get settings
        $options = get_option('migraine_chatbot_settings', array(
            'chatbot_enabled' => true,
            'api_url' => 'http://localhost:8000',
        ));
        
        // Don't render if disabled
        if (!$options['chatbot_enabled']) {
            return;
        }
        
        // Output chatbot widget
        echo '<script>
            (function() {
                // Configuration
                const widgetUrl = "' . esc_url($options['api_url']) . '";
                
                // Create script element
                const script = document.createElement("script");
                script.src = widgetUrl + "/widget.js";
                script.async = true;
                
                // Append to document
                document.body.appendChild(script);
            })();
        </script>';
    }
}

// Initialize the plugin
new MigraineChatbot(); 