angular.module('aiddataDET')
.controller('FiltersCtrl', function ($scope, $rootScope, $log, $stateParams, $state, $timeout, $location, $anchorScroll, queryFactory, filters, filterOptions) {
  // $scope.filterOrder = [ Array holding the order filters should appear in ]
  // $scope.filterOptions = { Options for a particular filter field }
  // $scope.filters = { Active Filters }
  // $scope.dataset = { Current Dataset Information }
  var resetting = false;

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
    var promise = $q.defer();
    $scope.dataset.fields[field].isActive = false;
    return promise;
    $timeout(function () {
      delete $scope.filters[field];
      _.pull($scope.filterOrder, field);
      promise.resolve(field);
    }, 300);
  };

  $scope.$watch('filters', function (newValue, oldValue) {
    if (!_.isEqual(newValue, oldValue) || resetting) {
      $scope.updateFilters();
    }
  }, true);

  $scope.$watch('filterOrder', function(newValue, oldValue) {
    if (!_.difference(newValue, oldValue)[0]) { return; }
    $timeout(function() {
      var w = d3.sum($('#searchModuleView').children().map(function() { return $(this).width(); }));
      console.log(w);
      $('#searchModuleView').animate({scrollLeft: w});
      $scope.dataset.fields[_.difference(newValue, oldValue)[0]].isActive = true;
    }, 400);

  }, true);

  $scope.$on('$viewContentLoaded', function (event) {
    $scope.ctrl = {};
    $scope.ctrl.items = _.range(0, 1000);
    $scope.filterOptions = filterOptions;
    $scope.filterOrder = _.cloneDeep(filterOptions.filterTypes);
    $scope.filters = queryFactory.filters;
    $scope.dataset = queryFactory.getDataset();
    broadcastUpdates();

    _.each($scope.filterOrder, function(f, i) {
      $scope.dataset.fields[f].isActive = true;
    });

  });

  $rootScope.$on('filters:reset', function() {
    resetting = true;
    for (var i = 0; i < $scope.filterOrder.length; i++ ) {
      $scope.toggleAll($scope.filterOrder[i]);
    }
    $timeout(function () {
      resetting = false;
      $scope.updateFilters();
    });
  });

  function broadcastUpdates () {
    $rootScope.$broadcast('filters:updated', filterOptions);
  }
});
