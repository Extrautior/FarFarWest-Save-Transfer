using System.Collections.ObjectModel;
using System.ComponentModel;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using Microsoft.Win32;

namespace FarFarWestSaveStudio;

public partial class MainWindow : Window
{
    private readonly ObservableCollection<SteamAccount> _accounts = [];
    private readonly ObservableCollection<string> _categories = [];
    private readonly ObservableCollection<InventoryEntry> _visibleEntries = [];
    private LoadedSave? _loadedSave;
    private List<InventoryEntry> _allEntries = [];

    public MainWindow()
    {
        InitializeComponent();
        PartySuffixBox.Text = SaveCore.DefaultPartySuffix;
        AccountsList.ItemsSource = _accounts;
        CategoryList.ItemsSource = _categories;
        InventoryGrid.ItemsSource = _visibleEntries;
        LoadAccounts();
    }

    private void SetPage(string page)
    {
        TransferPage.Visibility = page == "Transfer" ? Visibility.Visible : Visibility.Collapsed;
        EditorPage.Visibility = page == "Editor" ? Visibility.Visible : Visibility.Collapsed;
        ActivityPage.Visibility = page == "Activity" ? Visibility.Visible : Visibility.Collapsed;
        PageTitle.Text = page == "Editor" ? "Save Editor" : page;
        TransferNav.Background = page == "Transfer" ? (System.Windows.Media.Brush)Resources["Accent"] : System.Windows.Media.Brushes.Transparent;
        EditorNav.Background = page == "Editor" ? (System.Windows.Media.Brush)Resources["Accent"] : System.Windows.Media.Brushes.Transparent;
        ActivityNav.Background = page == "Activity" ? (System.Windows.Media.Brush)Resources["Accent"] : System.Windows.Media.Brushes.Transparent;
    }

    private void ShowTransfer(object sender, RoutedEventArgs e) => SetPage("Transfer");
    private void ShowEditor(object sender, RoutedEventArgs e) => SetPage("Editor");
    private void ShowActivity(object sender, RoutedEventArgs e) => SetPage("Activity");

    private void LoadAccounts()
    {
        _accounts.Clear();
        foreach (var account in SaveCore.DiscoverSteamAccounts())
        {
            _accounts.Add(account);
            _ = EnrichAccountAsync(account);
        }
        Log($"Found {_accounts.Count} local SteamID candidate(s).");
    }

    private async Task EnrichAccountAsync(SteamAccount account)
    {
        try
        {
            var profile = await SaveCore.FetchSteamProfileAsync(account.SteamId);
            Dispatcher.Invoke(() =>
            {
                var index = _accounts.IndexOf(account);
                if (index >= 0) _accounts[index] = profile;
            });
        }
        catch
        {
            // Local account name is fine.
        }
    }

    private void BrowseSource(object sender, RoutedEventArgs e)
    {
        var dialog = new OpenFileDialog
        {
            Title = "Choose Far Far West save",
            InitialDirectory = Directory.Exists(SaveCore.SaveDir) ? SaveCore.SaveDir : Environment.GetFolderPath(Environment.SpecialFolder.UserProfile),
            Filter = "Far Far West saves (*.save)|*.save|All files (*.*)|*.*"
        };
        if (dialog.ShowDialog(this) != true) return;
        SourceSaveBox.Text = dialog.FileName;
        DetectSource(sender, e);
        SetDefaultOutput();
    }

    private void BrowseOutput(object sender, RoutedEventArgs e)
    {
        var id = string.IsNullOrWhiteSpace(TargetSteamIdBox.Text) ? "edited" : TargetSteamIdBox.Text.Trim();
        var dialog = new SaveFileDialog
        {
            Title = "Choose output save",
            FileName = $"{id}.save",
            Filter = "Far Far West saves (*.save)|*.save|All files (*.*)|*.*"
        };
        if (dialog.ShowDialog(this) == true) OutputBox.Text = dialog.FileName;
    }

    private void DetectSource(object sender, RoutedEventArgs e)
    {
        try
        {
            SourceSteamIdBox.Text = SaveCore.InferSteamId(SourceSaveBox.Text);
            Log($"Source SteamID found: {SourceSteamIdBox.Text}");
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "SteamID", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private async void ResolveProfile(object sender, RoutedEventArgs e)
    {
        try
        {
            StatusText.Text = "Resolving profile...";
            var steamId = await SaveCore.ResolveSteamIdAsync(ProfileBox.Text);
            var profile = await SaveCore.FetchSteamProfileAsync(steamId);
            TargetSteamIdBox.Text = profile.SteamId;
            if (!_accounts.Any(a => a.SteamId == profile.SteamId)) _accounts.Insert(0, profile);
            SetDefaultOutput();
            StatusText.Text = "Profile resolved";
        }
        catch (Exception ex)
        {
            StatusText.Text = "Error";
            MessageBox.Show(this, ex.Message, "Steam profile", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void AccountSelected(object sender, SelectionChangedEventArgs e)
    {
        if (AccountsList.SelectedItem is not SteamAccount account) return;
        TargetSteamIdBox.Text = account.SteamId;
        SetDefaultOutput();
    }

    private void SetDefaultOutput()
    {
        if (string.IsNullOrWhiteSpace(SourceSaveBox.Text) || string.IsNullOrWhiteSpace(TargetSteamIdBox.Text)) return;
        OutputBox.Text = Path.Combine(Path.GetDirectoryName(SourceSaveBox.Text)!, $"{TargetSteamIdBox.Text.Trim()}.save");
    }

    private void TransferSave(object sender, RoutedEventArgs e)
    {
        try
        {
            var sourceId = string.IsNullOrWhiteSpace(SourceSteamIdBox.Text) ? SaveCore.InferSteamId(SourceSaveBox.Text) : SourceSteamIdBox.Text.Trim();
            var output = string.IsNullOrWhiteSpace(OutputBox.Text) ? Path.Combine(Path.GetDirectoryName(SourceSaveBox.Text)!, $"{TargetSteamIdBox.Text.Trim()}.save") : OutputBox.Text;
            SaveCore.TransferSave(SourceSaveBox.Text, output, sourceId, TargetSteamIdBox.Text.Trim(), PartySuffixBox.Text, RewriteCheck.IsChecked == true);
            StatusText.Text = "Transfer complete";
            Log($"Transferred save written: {output}");
            MessageBox.Show(this, "Transferred save written successfully.", "Transfer complete", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            StatusText.Text = "Error";
            MessageBox.Show(this, ex.Message, "Transfer", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void LoadEditorSave(object sender, RoutedEventArgs e)
    {
        try
        {
            if (string.IsNullOrWhiteSpace(SourceSaveBox.Text)) BrowseSource(sender, e);
            _loadedSave = SaveCore.LoadSave(SourceSaveBox.Text, SourceSteamIdBox.Text, PartySuffixBox.Text);
            _allEntries = _loadedSave.Entries.ToList();
            _categories.Clear();
            _categories.Add($"All ({_allEntries.Count})");
            foreach (var group in _allEntries.GroupBy(e => e.Category).OrderBy(g => g.Key))
                _categories.Add($"{group.Key} ({group.Count()})");
            CategoryList.SelectedIndex = 0;
            ApplyFilter();
            StatusText.Text = "Save loaded";
            EditorSummary.Text = $"{_allEntries.Count} editable runtimeInventory values loaded.";
            Log($"Loaded {_allEntries.Count} editable values using {_loadedSave.CryptoProfile}.");
            SetPage("Editor");
        }
        catch (Exception ex)
        {
            StatusText.Text = "Error";
            MessageBox.Show(this, ex.Message, "Save editor", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void CategorySelected(object sender, SelectionChangedEventArgs e) => ApplyFilter();
    private void FilterChanged(object sender, TextChangedEventArgs e) => ApplyFilter();

    private void ApplyFilter()
    {
        if (_allEntries.Count == 0) return;
        var categoryText = CategoryList.SelectedItem as string ?? "All";
        var category = categoryText.Split('(')[0].Trim();
        var search = SearchBox.Text.Trim();
        var filtered = _allEntries.Where(entry =>
            (category == "All" || entry.Category == category) &&
            (search.Length == 0 || entry.Name.Contains(search, StringComparison.OrdinalIgnoreCase)));
        _visibleEntries.Clear();
        foreach (var entry in filtered) _visibleEntries.Add(entry);
        EditorSummary.Text = $"{_visibleEntries.Count} values shown.";
    }

    private void SaveEdited(object sender, RoutedEventArgs e)
    {
        try
        {
            if (_loadedSave is null) throw new InvalidOperationException("Load a save first.");
            InventoryGrid.CommitEdit(DataGridEditingUnit.Cell, true);
            InventoryGrid.CommitEdit(DataGridEditingUnit.Row, true);
            var dialog = new SaveFileDialog
            {
                Title = "Save edited Far Far West save",
                FileName = string.IsNullOrWhiteSpace(OutputBox.Text) ? $"{_loadedSave.SteamId}.save" : Path.GetFileName(OutputBox.Text),
                InitialDirectory = string.IsNullOrWhiteSpace(OutputBox.Text) ? SaveCore.SaveDir : Path.GetDirectoryName(OutputBox.Text),
                Filter = "Far Far West saves (*.save)|*.save|All files (*.*)|*.*"
            };
            if (dialog.ShowDialog(this) != true) return;
            SaveCore.SaveEdited(dialog.FileName, _loadedSave, _allEntries, PartySuffixBox.Text);
            Log($"Edited save written: {dialog.FileName}");
            MessageBox.Show(this, "Edited save written successfully.", "Save editor", MessageBoxButton.OK, MessageBoxImage.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show(this, ex.Message, "Save editor", MessageBoxButton.OK, MessageBoxImage.Error);
        }
    }

    private void Log(string message)
    {
        LogBox.AppendText($"[{DateTime.Now:HH:mm:ss}] {message}{Environment.NewLine}");
        LogBox.ScrollToEnd();
    }
}
