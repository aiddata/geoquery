angular.module('aiddataDET')
.controller('FiltersCtrl', function ($scope, $rootScope, $log, $stateParams, $state, $timeout, $location, $anchorScroll, queryFactory, filters, filterOptions) {
  // $scope.filterOrder = [ Array holding the order filters should appear in ]
  // $scope.filterOptions = { Options for a particular filter field }
  // $scope.filters = { Active Filters }
  // $scope.dataset = { Current Dataset Information }

  $scope.updateFilters = function () {
    queryFactory.updateFilters()
      .then(function (filterOptions) {
        $scope.filterOptions = filterOptions;
        broadcastUpdates();
      });
  };

  $scope.toggleAll = function (filter) {
    return $scope.dataset.fields[filter].type === 'list' ?
      queryFactory.resetFilter(filter) : queryFactory.resetFilterRange(filter);
  };

  $scope.removeFilter = function(field) {
    $scope.dataset.fields[field].isActive = false;
    $timeout(function () {
      delete $scope.filters[field];
      _.pull($scope.filterOrder, field);
    }, 300);
  };

  $scope.$watch('filters', function (newValue, oldValue) {
    if (!_.isEqual(newValue, oldValue)) {
      $scope.updateFilters();
    }
  }, true);

  $scope.$watch('filterOrder', function(newValue, oldValue) {
    if (!_.difference(newValue, oldValue)[0]) { return; }
    $timeout(function() {
      $location.hash('addFilterButton');
      $anchorScroll();
      $scope.dataset.fields[_.difference(newValue, oldValue)[0]].isActive = true;
    }, 300);

  }, true);

  $scope.$on('$viewContentLoaded', function (event) {
    $scope.filterOptions = filterOptions;
    $scope.filterOrder = _.cloneDeep(filterOptions.filterTypes);
    $scope.filters = queryFactory.filters;
    $scope.dataset = queryFactory.getDataset();
    broadcastUpdates();

    _.each($scope.filterOrder, function(f, i) {
      $scope.dataset.fields[f].isActive = true;
    });

  });

  function broadcastUpdates () {
    $rootScope.$broadcast('filters:updated', filterOptions);
  }
});
