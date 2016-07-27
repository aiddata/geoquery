angular.module('aiddataDET')
.controller('FiltersCtrl', function ($scope, $rootScope, $log, queryFactory, $stateParams, $state, filters, filterOptions) {
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
    queryFactory.resetFilter(filter);
  };

  $scope.removeFilter = function(field) {
    delete $scope.filters[field];
    _.pull($scope.filterOrder, field);
  };

  $scope.$watch('filters', function (newValue, oldValue) {
    if (!_.isEqual(newValue, oldValue)) {
      $scope.updateFilters();
    }
  }, true);

  $scope.$on('$viewContentLoaded', function (event) {
    $scope.filterOptions = filterOptions;
    $scope.filterOrder = _.cloneDeep(filterOptions.filterTypes);
    $scope.filters = queryFactory.filters;
    $scope.dataset = queryFactory.getDataset();
    broadcastUpdates();
  });

  function broadcastUpdates () {
    $rootScope.$broadcast('filters:updated', filterOptions);
  }
});
