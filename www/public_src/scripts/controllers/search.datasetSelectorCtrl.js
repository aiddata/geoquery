/**
  * This is the controller for the dataset selectior on the 'customize datasets'
  * page.  It is responsible for displaying, filtering, and selecting datasets.
  */
angular.module('aiddataDET')
.controller('DatasetSelectorCtrl', function($scope, $rootScope, $log, $timeout, datasets, $state, $window, $element, info, queryFactory) {
  $scope.showSearchTools = false;   // Advanced Search Visibility
  $scope.featuredTags = [];         // Featured Category Tags
  $scope.querySize = 0;
  $scope.listStyle = { };

  // Datasets container
  $scope.datasets = {
    filtered: [],
    options: [],
    selected: ''
  };

  // Filter Fields
  $scope.fields = {
    options: [{ display: 'Date Updated', value: 'date_updated'}, { display: 'Name', value: 'title'}],
    selected: '',
    descending: true
  };

  // Search datasets by tags or title
  $scope.search = function (item) {
    if ($scope.dataFilters.tag !== 'all' &&
      item.extras.tags.indexOf($scope.dataFilters.tag) < 0 ) {
      return false;
    }

    return _.chain(item.extras.tags)
      .concat(item.title)
      .join(', ')
      .toLower()
      .includes(_.toLower($scope.dataFilters.searchText))
      .value();
  };

  // Select dataset
  $scope.selectDataset = function(dataset) {
    var targetState = dataset.type === 'release' ? 'search.filters' :
        'search.options';

    $log.debug('Navigating to: ', targetState);

    $scope.datasets.selected = dataset.name;

    $state.go(targetState, { dataset: dataset.name });

  };

  // When the number of filtered datasets changes - select the dataset that appears on top
  $scope.$watch('datasets.filtered', function (newValue, oldValue) {
    if (_.find($scope.datasets.filtered, { name: $scope.datasets.selected }) ||
      !$scope.datasets.selected ||
      newValue.length === 0) {
      return;
    }
    // // Decide which dataset appears on top according to how they are currently arranged
    if ($scope.fields.descending) {
      $scope.selectDataset(_.last($scope.datasets.filtered));
    } else {
      $scope.selectDataset(_.first($scope.datasets.filtered));
    }
  }, true);

  $rootScope.$on('query:updated', function() {
    $scope.querySize = queryFactory.querySize();
  });

  // Define default data filters and order datasets
  $scope.$on('$viewContentLoaded', function(event) {
    if ($state.params.dataset) {
      $scope.datasets.selected = $state.params.dataset;
    } else if (queryFactory.getDataset()) {
      $scope.datasets.selected = queryFactory.getDataset();
    }
    $scope.dataFilters = { searchText: '', tag: 'all' };
    $scope.featuredTags = info.data_categories;

    var d = _.orderBy(datasets, 'type');      // Position AidData Datasets at the Top of Array
    $scope.datasets.options = d;
    $scope.querySize = queryFactory.querySize();
  });


  /* Mananage List Size */
  var searchContent = document.querySelector('#search-content'),
      searchTools = document.querySelector('#datasetSelector .search-tools'),
      minHeight = 500;

  $scope.$watch(
    function() { return searchTools.offsetHeight; },
    function() { setListHeight(); }
  );

  angular.element($window).bind('resize', function() {
    $timeout(function() { setListHeight(); });
  });

  function setListHeight () {
    var contentHeight = searchContent.offsetHeight,
        toolsHeight = searchTools.offsetHeight,
        searchHeight = contentHeight < minHeight ? minHeight : contentHeight,
        listHeight = searchHeight - toolsHeight + 'px';

    $scope.listStyle['max-height'] = listHeight;
    $scope.listStyle['height'] = listHeight;
  }
});
