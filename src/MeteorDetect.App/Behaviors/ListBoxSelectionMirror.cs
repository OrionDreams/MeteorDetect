using System.Collections;
using Avalonia;
using Avalonia.Controls;

namespace MeteorDetect.App.Behaviors;

public static class ListBoxSelectionMirror
{
    public static readonly AttachedProperty<IList?> SelectedItemsProperty =
        AvaloniaProperty.RegisterAttached<ListBox, IList?>(
            "SelectedItems",
            typeof(ListBoxSelectionMirror));

    public static void SetSelectedItems(AvaloniaObject element, IList? value)
    {
        element.SetValue(SelectedItemsProperty, value);
    }

    public static IList? GetSelectedItems(AvaloniaObject element)
    {
        return element.GetValue(SelectedItemsProperty);
    }

    static ListBoxSelectionMirror()
    {
        SelectedItemsProperty.Changed.AddClassHandler<ListBox>(OnSelectedItemsPropertyChanged);
    }

    private static void OnSelectedItemsPropertyChanged(ListBox listBox, AvaloniaPropertyChangedEventArgs e)
    {
        listBox.SelectionChanged -= OnSelectionChanged;
        if (GetSelectedItems(listBox) is not null)
        {
            listBox.SelectionChanged += OnSelectionChanged;
            MirrorSelection(listBox);
        }
    }

    private static void OnSelectionChanged(object? sender, SelectionChangedEventArgs e)
    {
        if (sender is ListBox listBox)
        {
            MirrorSelection(listBox);
        }
    }

    private static void MirrorSelection(ListBox listBox)
    {
        var target = GetSelectedItems(listBox);
        if (target is null)
        {
            return;
        }

        target.Clear();
        var selectedItems = listBox.SelectedItems;
        if (selectedItems is null)
        {
            return;
        }

        foreach (var item in selectedItems)
        {
            target.Add(item);
        }
    }
}
